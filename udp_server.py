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

def sign(num):
    if num >= 0:
        return 1
    else:
        return -1

def transfer():
    return 0

def getTarget():
    tz = zoneinfo.ZoneInfo("Europe/Busingen")
    local = datetime.datetime.now(tz).time()
    #log(local)
    if local < datetime.time(5, 0):
        return -0
    if local < datetime.time(8, 30):
        return -0
    if local < datetime.time(9, 0):
        return -0
    if local < datetime.time(11, 0):
        return -0
    if local < datetime.time(19, 30):
        return -350
    if local < datetime.time(22, 30):
        return -350
    return -0


integralAdjust = 0
replyCounter = 0

def getAnswer():
    global replyCounter
    global integralAdjust
    filePath = f"{promDir}/lastResults.json"
    with open(filePath, 'r') as file:
        lastResults = json.load(file)


    try:
        filePath = f"{promDir}/plugs.json"
        with open(filePath, 'r') as file:
            plugs = json.load(file)
    except:
        plugs = {}
        pass

    plugEcoflow = plugs.get("ecoflow_stream_ultra_x_1")
    if plugEcoflow:
        ecoflowPower = plugEcoflow.get("apower")

    plugMarstek = plugs.get("marstek_jupiter_c_1")
    if plugMarstek:
        marstekPower = plugMarstek.get("apower")

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

    if maxPower["total_act_power"] > 1400:
        #reference = [ latest ]
        reference = lastTwo
    else:
        # with as much damping and all the other stuff, use only more recent data now
        reference = lastThree


    for key in powerKeys:
        vals = [ stuff.get(key) for stuff in reference ]

        minPower[key] = round(min(vals))
        maxPower[key] = round(max(vals))
        avgPower[key] = round(sum(vals) / len(vals))

    if False and latest["total_act_power"] < 800:
        total = latest["total_act_power"]
    else:
        total = minPower["total_act_power"]


    target = " "

    targetDiff = 0
    preTargetTotal = total
    if not transfer() and marstekPower is not None and ecoflowPower is not None:
        targetDiff = marstekPower - getTarget()

        #log(f'targetDiff: {marstekPower} - {getTarget()} = {targetDiff}')

        ecoAdjusted = ecoflowPower - 15

        if total - targetDiff < ecoAdjusted:
            targetDiffAdjusted = total - ecoAdjusted
            #log(f'targetDiffAdjusted restricted by ecoflowPower, setting targetDiffAdjusted to {total} - {ecoflowPower} = {targetDiffAdjusted}')
        else:
            targetDiffAdjusted = targetDiff

        if ecoAdjusted > 0:
            total = -ecoAdjusted
            #log(f"ecoflow too much {ecoAdjusted}")
            target = "--"
        elif targetDiffAdjusted > total:
            #log(f'targetDiffAdjusted > total: {targetDiffAdjusted} > {total}')
            total = min(200, targetDiffAdjusted)
            target = "+"
        elif ecoAdjusted > -800 and targetDiff < 0 and ecoflowPower < 0:
            # slightly bleed down power if ecoflow still has more power to give
            total -= 25
            target = "-"

    # push power into the grid so the other battery picks it up
    total += transfer()

    undampedTotal = round(total)

    if total < -800:
        total = -800

    if abs(total) < 100:
        # extra dampening for low powers
        total *= 0.5
    else:
        if total > 0:
            total *= 1
        if total < 0:
            total *= 1

    # global dampening
    total *= 0.5

    # minimum the inverter will react to
    minStep = 11

    # if undamped adjustment required is less than minStep, can't do any better, reset the integral
    # adjustment
    if abs(undampedTotal) < minStep * 0.75:
        integralAdjust = 0

    if abs(total) < minStep:
        # another dampening factor for these VERY small adjustments
        # better to just keep it stable
        integralAdjust += total * 0.75
        if abs(integralAdjust) > minStep:
            total = minStep * sign(integralAdjust)
            integralAdjust = 0
        else:
            total = 0
    else:
        # use integral adjust only for successive intervals with little inputs
        integralAdjust = 0

    total = round(total)
    undampedTotal = round(undampedTotal)
    targetDiff = round(targetDiff)
    preTargetTotal = round(preTargetTotal)

    log(f"Responding with total: {total:4} undampedTotal: {undampedTotal:4} target: {target} targetDiff: {targetDiff:4} preTargetTotal: {preTargetTotal:4} integralAdjust: {round(integralAdjust, 1)}")

    mod = dict()
    mod["id"] = 0
    mod["a_act_power"] = 0
    mod["b_act_power"] = total
    mod["c_act_power"] = 0

    mod["total_act_power"] = sum([ mod[k] for k in phaseKeys ])

    for key in powerKeys:
        mod[key] = round(mod[key])

    resp = dict()
    resp["id"] = 0
    resp["src"] = "shellypro3em-c0ffee"
    resp["result"] = mod
    #log(resp)
    replyCounter += 1
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
