#!/usr/bin/env python3

import urllib.request
import json
import traceback
import sys
import time
import threading
import os

def log(msg = "no log message provided"):
    if (type(msg) != str):
        msg = str(msg)
    msg = msg.strip()
    print(msg, file=sys.stderr)

def logExceptionOnly(ex):
    lines = traceback.format_exception_only(ex)
    log(lines[0])

def sleepTruncatedInterval(interval=1.0, offset=0.0):
    now = time.time()
    sleepFor = interval - ((now - offset) % interval)
    time.sleep(sleepFor)

    #if sleepFor > 1 or sleepFor < 0.8:
    #    log(f"slept for {sleepFor}, time now {time.time()}")


plugs = [
        { "name": "ecoflow_stream_ultra_x_1", "url": "http://192.168.7.23", },
        { "name": "marstek_jupiter_c_1",     "url": "http://192.168.7.24", },
        ]

promDir = "/run/shelly_shim"
interval = 1.0

if not os.path.exists(promDir):
    os.mkdir(promDir)

def generateProm(plug=None, data=None, interval=None):
    if not plug or not data or not interval:
        log('generateProm called without plug, data or interval argument')
        return

    counterKeys = [
            "a", # power added
            ]

    gauges = [
            "voltage",
            "apower", # do power as gauge even if there is already the watt seconds counter
            ]

    if not plug.get("counters"):
        # set up energy counters if they don't exist already
        # counters in Watt seconds
        plug["counters"] = {}

        for key in counterKeys:
            plug["counters"][key] = 0.0
            plug["counters"][key + "_ret"] = 0.0

    out = ""
    for key in gauges:
        value = data.get(key)
        if value == None:
            log(f"json missing key: {key}")
            continue
        promKey = f"{plug["name"]}_{key}"
        out += f"# TYPE {promKey} gauge\n"
        out += f"{promKey} {value}\n"

    for key in counterKeys:
        value = plug["counters"][key]
        retValue = plug["counters"][key + "_ret"]
        power = data.get(key + "power")
        if power == None:
            log(f"json missing key: {key}")
            continue

        power = float(power)
        if power > 0.0:
            value += float(power) * interval
        else:
            retValue -= float(power) * interval

        plug["counters"][key] = value
        plug["counters"][key + "_ret"] = retValue

        promKey = f"{plug["name"]}_{key}_watt_seconds"
        out += f"# TYPE {promKey} counter\n"
        out += f"{promKey} {round(value, 1)}\n"

        promKey = f"{plug["name"]}_{key}_ret_watt_seconds"
        out += f"# TYPE {promKey} counter\n"
        out += f"{promKey} {round(retValue, 1)}\n"

    return out

def handlePlug(plug=None, interval=1.0):
    if not plug:
        log('handlePlug called without plug argument')
        return

    offset = 0.05
    attempts = 2
    cushion = 0.15
    timeout = (interval - offset - cushion) / attempts
    timeout = round(timeout, 3)

    log(f'handling plug {plug["name"]} with URL {plug["url"]} (using {attempts} attemps with timeout {timeout}s)')

    elapsed = 0
    lastUpdate = round(time.time(), 3)
    while True:
        sleepTruncatedInterval(interval=interval, offset=offset)

        startOfInterval = round(time.time(), 3)

        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(f"{plug["url"]}/rpc/Switch.GetStatus?id=0", timeout=timeout) as response:
                    data = json.load(response)

                plug["data"] = data
                plug["prom"] = generateProm(plug=plug, data=data, interval=interval)

                now = round(time.time(), 3)
                #elapsed = round(now - lastUpdate, 3)
                lastUpdate = now

                plug["lastUpdate"] = lastUpdate

                break
            except urllib.error.URLError as ex:
                if "timed out" in str(traceback.format_exception_only(ex)):
                    now = round(time.time(), 3)
                    if False and attempt != 0:
                        log(f"timeout for attempt {attempt} at {now}")
                else:
                    log(traceback.format_exception_only(ex))
                    logExceptionOnly(ex)
            except TimeoutError as ex:
                now = round(time.time(), 3)
                if False and attempt != 0:
                    log(f"timeout for attempt {attempt} at {now}")
            except Exception:
                log(traceback.format_exc())

            if attempt == attempts - 1:
                log(f"WARNING: no data for interval {startOfInterval} for plug {plug["name"]}")


for plug in plugs:
    thread = threading.Thread(
            target=handlePlug,
            kwargs={
                "plug": plug,
                "interval": interval,
                },
            daemon=True,
            )
    thread.start()


# write prom file in main thread after end of collection period
while True:
    sleepTruncatedInterval(interval=interval, offset=0.95)
    promData = ""
    jsonData = {}
    for plug in plugs:
        if plug.get("prom"):
            promData += plug["prom"]
        if plug.get("data"):
            jsonData[plug["name"]] = plug["data"]

    filePath = f"{promDir}/plugs.prom"
    tmpPath = filePath + ".tmp"
    with open(tmpPath, "w") as file:
        file.write(promData)
        os.rename(tmpPath, filePath)

    filePath = f"{promDir}/plugs.json"
    tmpPath = filePath + ".tmp"
    with open(tmpPath, "w") as file:
        json.dump(jsonData, file, indent=2)
    os.rename(tmpPath, filePath)
