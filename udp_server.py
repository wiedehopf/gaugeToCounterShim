#!/usr/bin/env python3

# don't use this unless you really understand what it does
# it's a messy hack to adjust the behaviour of a Marstek inverter which gets the power to compensate
# for via shelly RPC on UDP


# bootstrap port forward (starts out as multicast): ssh p1 "socat -d -d udp4-listen:1010,reuseaddr udp:192.168.2.16:1010"

import json
import traceback
import sys
import time
import os
import threading
import socket

def log(msg = "no log message provided"):
    if (type(msg) != str):
        msg = str(msg)
    msg = msg.strip()
    print(msg, file=sys.stderr)

def logExceptionOnly(ex):
    lines = traceback.format_exception_only(ex)
    log(lines[0])

port = 1010

meterIp = "192.168.7.7"
meterPort = 1010

def modifyAnswer(txt):
    resp = json.loads(txt)
    powerKeys = [
            "a_act_power",
            "b_act_power",
            "c_act_power",
            ]

    res = resp["result"]

    total_power = 0
    for key in powerKeys:
        avg = 0
        power = round(res[key] - 5)
        res[key] = power
        total_power += power

    res["total_act_power"] = total_power

    return json.dumps(resp)


# Define server address and port
# Use "0.0.0.0" to listen on all available network interfaces
bind = "0.0.0.0" 
port = 1010

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((bind, port))

log(f"UDP server listening on {bind}:{port}")

client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
client.settimeout(0.3)

while True:
    data, addr = sock.recvfrom(1024)

    try:
        message = data.decode()
        log(f"Msg from {addr}: {message}")
    except Exception as ex:	
        log(traceback.format_exc())
        continue

    msg = b'{"id":0,"method":"EM.GetStatus","params":{"id":0}}\n'
    client.sendto(msg, (meterIp, meterPort))

    try:
        raw, server = client.recvfrom(1024)
    except TimeoutError as ex:
        continue

    response = modifyAnswer(raw)

    if response:
        sock.sendto(response.encode(), addr)
