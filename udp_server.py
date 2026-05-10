#!/usr/bin/env python3

# don't use this unless you really understand what it does
# it's a messy hack to adjust the behaviour of a Marstek inverter which gets the power to compensate
# for via shelly RPC on UDP
# shelly UDP RPC seems to be buggy plus we are already getting the data every second via http
# so we just use the data from the shelly_shim and mess with it to adjust for this very particular
# situation

import datetime
import json
import os
import random
import socket
import sys
import threading
import time
import traceback
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
    if local < datetime.time(6, 0):
        return -0
    if local < datetime.time(8, 0):
        return -400
    if local < datetime.time(9, 30):
        return -200
    if local < datetime.time(10, 30):
        return -400
    if local < datetime.time(11, 30):
        return -400
    if local < datetime.time(16, 30):
        return -0
    if local < datetime.time(18, 30):
        return -0
    if local < datetime.time(19, 30):
        return -100
    if local < datetime.time(23, 30):
        return -400
    return -0


integralAdjust = 0
replyCounter = 0

emptyTimeout = time.time()
lastOutput = 0
lastTotals = []
lastMarstekPower = None
ecoflowHistory = []

def getAnswer():
    global replyCounter
    global integralAdjust
    global lastOutput
    global emptyTimeout
    global lastTotals
    global lastMarstekPower
    global ecoflowHistory
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
    else:
        ecoflowPower = None

    plugMarstek = plugs.get("marstek_jupiter_c_1")
    if plugMarstek:
        marstekPower = plugMarstek.get("apower")
    else:
        marstekPower = None

    ecoflowHistory = ecoflowHistory[:10]
    ecoflowHistory.append(ecoflowPower or 0)
    ecoflowActive = any((x < -15 or x > 15) for x in ecoflowHistory)

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

    total = minPower["total_act_power"]

    target = " "

    targetDiff = 0
    preTargetTotal = total

    if not transfer() and marstekPower is not None and ecoflowPower is not None:
        targetDiff = marstekPower - getTarget()

        #log(f'targetDiff: {marstekPower} - {getTarget()} = {targetDiff}')

        ecoAdjusted = ecoflowPower

        if targetDiff > total - ecoAdjusted:
            targetDiffAdjusted = total - ecoAdjusted
            #log(f'targetDiffAdjusted restricted by ecoflowPower, setting targetDiffAdjusted to {total} - {ecoflowPower} = {targetDiffAdjusted}')
        else:
            targetDiffAdjusted = targetDiff

        if abs(targetDiff) < 5 and ecoflowPower > -600 and marstekPower > -1 and total < 300 and ecoflowActive:
            # let the ecoflow do all the work
            total = 0
            target = "e"
        elif ecoAdjusted > 15:
            # ecoflow charging battery from AC
            if False and total > 100:
                # just wait, ecoflow should reduce charging / start delivering power again due to
                # the total being > 20
                total = 0
                target = "--0"
            else:
                # reduce inverter power to inhibit transferring battery power from marstek to
                # ecoflow
                total = min(min(-ecoAdjusted, total), targetDiff)
                #log(f"ecoflow too much {ecoAdjusted}")
                target = "--"
        elif targetDiffAdjusted > 0 and targetDiffAdjusted > total:
            #log(f'targetDiffAdjusted > total: {targetDiffAdjusted} > {total}')
            total = targetDiffAdjusted
            target = "+"
        elif ecoflowPower > -800 and targetDiff < -11 and ecoflowActive:
            # slightly bleed down power if ecoflow still has more power to give
            total = min(-20, targetDiff * 0.5)
            target = "-"

    # push power into the grid so the other battery picks it up
    total += transfer()

    # slight offset bias
    total += 3

    undampedTotal = total

    if transfer():
        if total > 0:
            total *= 1.2
        if total < 0:
            total *= 0.8
    elif abs(total) < 101:
        # dampening for low power diff
        if total > 0:
            total *= 0.5
        else:
            total *= 0.5
    elif abs(total) < 201:
        if total > 0:
            total *= (0.5 + ((abs(total) - 100) / 100) * 1.0)
        else:
            total *= (0.5 + ((abs(total) - 100) / 100) * 0.2)
    else:
        # dampening for high power diff
        if total > 0:
            total *= 1.5
        else:
            total *= 0.7

    # global dampening
    total *= 0.5

    if total < 0:
        # power reduction needs dampening to adjust for weird Marstek behaviour
        total *= 0.5

    # limit negative power reduction
    if total < -200:
        total = -200

    # minimum the inverter will react to
    minStep = 11
    minStepDown = -4

    if (total > 0 and total <= minStep) or (total < 0 and total >= minStepDown):
        # extra dampen for stepping
        total *= 0.5

        if abs(undampedTotal) > 8:
            integralAdjust += total
        else:
            integralAdjust *= 0.8

        if integralAdjust >= minStep:
            total = minStep
            integralAdjust = 0
        elif integralAdjust <= minStepDown:
            # when trying to reduce power,
            # smaller step needs to be sent to get the smallest step
            total = minStepDown
            integralAdjust = 0
        else:
            total = 0

    else:
        # use integral adjust only for successive intervals with little inputs
        integralAdjust *= 0.8


    if marstekPower is not None:
        # no power requested, assume it gives output when requested
        if total < 2 * minStep:
            lastOutput = now

        # actual power output
        if marstekPower < -10:
            lastOutput = now

        if lastMarstekPower is not None:
            # last request was not to reduce power but power has reduced significantly
            if not any(x < -20 for x in lastTotals) and marstekPower > lastMarstekPower + 200:
                # timeout if it is detected that the battery is empty and it's giving stupid
                # short power bursts before turning off again
                log(lastTotals)
                emptyTimeout = now + 2 * 60

    if now < emptyTimeout:
        # don't ask for any power for a while when empty battery is detected
        target = "0"
        total = -800

    # possibly the marstek firmware doesn't like when it gets only zeroes
    total += sign(total) * 0.1 * random.random()

    total = round(total, 1)
    undampedTotal = round(undampedTotal, 1)
    targetDiff = round(targetDiff)
    preTargetTotal = round(preTargetTotal)

    lastTotals = [total] + lastTotals[:5]

    lastMarstekPower = marstekPower

    marstekFormatted = "None" if marstekPower is None else -round(marstekPower)
    ecoflowFormatted = "None" if ecoflowPower is None else -round(ecoflowPower)

    log(f"power: {marstekFormatted:4} req.: {total:7} epower: {ecoflowFormatted:4} undampedTotal: {undampedTotal:7} target: {target:4} targetDiff: {targetDiff:4} preTargetTotal: {preTargetTotal:4} integralAdjust: {round(integralAdjust, 1)}")

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
