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
promDir = "/run/shelly_shim"

def getAnswer():
    filePath = f"{promDir}/lastResults.json"
    with open(filePath, 'r') as file:
        lastResults = json.load(file)


    now = time.time()
    lastThree = {k: v for k, v in lastResults.items() if float(k) > now - 3}

    if len(lastThree) < 1:
        log('no answer: no data for last 3 seconds')
        return None

    latestKey = sorted(lastThree.keys(), reverse=True)[0]
    #log(now - float(latestKey))
    latest = lastThree.get(latestKey)

    mod = json.loads(json.dumps(latest))

    powerKeys = [
            "a_act_power",
            "b_act_power",
            "c_act_power",
            ]

    total_power = 0
    for key in powerKeys:
        avg = 0
        vals = []
        for stuff in lastThree.values():
            val = stuff.get(key)
            vals.append(val)
            avg += val

        avg = round(avg / len(vals))

        power = round(min(vals)) - 2
        total_power +=  power
        mod[key] = power

    mod["total_act_power"] = total_power

    resp = dict()
    resp["id"] = 0
    resp["src"] = "shellypro3em-bfefd9c87ec9"
    resp["result"] = mod
    return json.dumps(resp)


# Define server address and port
# Use "0.0.0.0" to listen on all available network interfaces
bind = "0.0.0.0" 
port = 1010

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((bind, port))

log(f"UDP server listening on {bind}:{port}")

while True:
    data, addr = sock.recvfrom(1024)

    try:
        message = data.decode()
        log(f"Msg from {addr}: {message}")
    except Exception as ex:	
        log(traceback.format_exc())
        continue

    response = getAnswer()
    if response:
        sock.sendto(response.encode(), addr)
