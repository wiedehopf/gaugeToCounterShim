#!/usr/bin/env python3

# don't use this unless you really understand what it does
# it's a messy hack to adjust the behaviour of a Marstek inverter which gets the power to compensate
# for via shelly RPC on UDP
# shelly UDP RPC seems to be buggy plus we are already getting the data every second via http
# so we just use the data from the shelly_shim and mess with it to adjust for this very particular
# situation

import json
import traceback
import sys
import time
import os
import threading
import socket
import datetime
import zoneinfo

def log(msg = "no log message provided"):
    if (type(msg) != str):
        msg = str(msg)
    msg = msg.strip()
    print(msg, file=sys.stderr, flush=True)

def logExceptionOnly(ex):
    lines = traceback.format_exception_only(ex)
    log(lines[0])

port = 1010
promDir = "/run/shelly_shim"


def getBTarget():
    tz = zoneinfo.ZoneInfo("Europe/Busingen")
    local = datetime.datetime.now(tz).time()
    #log(local)
    # large number == no target
    # heat up marstek
    if local < datetime.time(4, 0):
        return 5000
    if local < datetime.time(8, 30):
        return -60
    if local < datetime.time(11, 0):
        return -100
    if local < datetime.time(19, 30):
        return 5000
    return -120


integralAdjust = 0

def getAnswer():
    global integralAdjust
    filePath = f"{promDir}/lastResults.json"
    with open(filePath, 'r') as file:
        lastResults = json.load(file)


    now = time.time()
    lastFiveSeconds = { k: v for k, v in lastResults.items() if float(k) > now - 5 }
    if len(lastFiveSeconds) < 1:
        log('no answer: no data for last 5 seconds')
        return None

    resultsOrdered = [ lastResults[k] for k in sorted(lastResults.keys()) ]
    lastTwo = resultsOrdered[-2:]
    lastThree = resultsOrdered[-3:]
    lastFour = resultsOrdered[-4:]
    lastFive = resultsOrdered[-5:]

    latest = resultsOrdered[-1]

    mod = json.loads(json.dumps(latest))

    phaseKeys = [
            "a_act_power",
            "b_act_power",
            "c_act_power",
            ]

    powerKeys = phaseKeys + [ "total_act_power" ]

    avgPower = {}
    minPower = {}
    maxPower = {}

    for key in powerKeys:
        vals = [ stuff.get(key) for stuff in lastFive ]

        minPower[key] = round(min(vals))
        maxPower[key] = round(max(vals))
        avgPower[key] = round(sum(vals) / len(vals))

    if latest["a_act_power"] > -10 or maxPower["total_act_power"] > 1400:
        #reference = [ latest ]
        reference = lastTwo
    else:
        reference = lastFive

    for key in powerKeys:
        vals = [ stuff.get(key) for stuff in reference ]

        minPower[key] = round(min(vals))
        maxPower[key] = round(max(vals))
        avgPower[key] = round(sum(vals) / len(vals))

    if False and latest["total_act_power"] < 800:
        total = latest["total_act_power"]
    else:
        total = minPower["total_act_power"]


    bTargetDiff = minPower["b_act_power"] - getBTarget()
    if bTargetDiff > total:
        total = bTargetDiff

    undampedTotal = total

    # bias towards supplying less power when providing a lot of it
    if minPower["b_act_power"] < -400:
        total -= 25
    elif minPower["b_act_power"] < -150:
        total -= 15
    else:
        total -= 5

    if abs(total) > 4:
        integralAdjust += total / abs(total)

    if total < -800:
        total = -800

    if abs(total) < 100:
        #dampen
        if abs(total) > 9:
            # reduce absolute value by 10
            total -= 5 * (total / abs(total))
        total *= 0.8
    else:
        if total > 0:
            # dampen as well but not as much
            total *= 0.7
        if total < 0:
            # dampen power reduction massively for large power to avoid coupled oscillation with
            # other inverter
            total *= 0.3

    if abs(total) < 11:
        if abs(integralAdjust) > 5:
            total = 11 * integralAdjust / abs(integralAdjust)
            integralAdjust = 0
        else:
            total = 0


    mod = dict()
    mod["id"] = 0
    mod["a_act_power"] = 0
    mod["b_act_power"] = total
    mod["c_act_power"] = 0

    mod["total_act_power"] = sum([ mod[k] for k in phaseKeys ])

    for key in powerKeys:
        mod[key] = round(mod[key])

    log(f"Responding with total_act_power: {mod['total_act_power']} undampedTotal: {undampedTotal}")

    resp = dict()
    resp["id"] = 0
    resp["src"] = "shellypro3em-c0ffee"
    resp["result"] = mod
    #log(resp)
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
        #log(f"Msg from {addr}: {message}")
    except Exception as ex:	
        log(traceback.format_exc())
        continue

    response = getAnswer()
    if response:
        sock.sendto(response.encode(), addr)
