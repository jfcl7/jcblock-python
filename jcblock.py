#! /usr/bin/python3
#
# jcblock.py - junk call block using AT USB modem
#
# Copyright (c) 2021 by Tom Porcher
#
# Copy permission:
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You may view a copy of the GNU General Public License at:
#     <http://www.gnu.org/licenses/>.
#
# Based on jcblockAT.c by Walter S. Heath (2018).
#
# jcblock.py provides all the functionality of jcblockAT.c
#
# jcblock.py adds the capability of using a regular expression to match the
# name or number in the incoming caller ID.
#
# The allow list and block list file format is different from jcblockAT.c.
# See the format descriptions below.
#

#
# allow/block list files:
#    allowlist.dat
#    blocklist.dat
#    format:
#        <pattern>;<flags>;<comment>
#        ^\w+\s+\w\w$;  p  ;this is <city> <st>
#    <flags>: p -> entry will never be purged
#    note: <pattern> includes any surrounding whitespace so ";" should
#          immediately follow <pattern>.
#          ";" can be included in <pattern> with "\;"
#
# match files (keeps match history):
#    allowlist.dat-match
#    blocklist.dat-match
#    format:
#        <timestamp>;<count>;<pattern>
#        2021-10-06 17:01;2;^\w+\s+\w\w$
#
# call log:
#    calllog.log
#    format:
#        <timestamp>;<number>;<name>;<block/allow>
#
# All matches are case-insensitive
# Matches are applied to the Caller ID number and name fields separately
#
# Picking up a phone and pressing the "*" key within 10 seconds will add the
# current calling number to the block list
# 
# SIGHUP will force reloading of the allow/block lists before the next call
#

import sys
import os
import time
import signal
import serial
import re
import functools
print = functools.partial(print, flush=True)

# configuration
allowlist_file = "allowlist.dat"
blocklist_file = "blocklist.dat"
calllog_file   = "calllog.log"
modem_port     = "/dev/ttyACM0"
blocklist_purge_days = 1
blocklist_lifetime_days = 9*30

day_secs = 24*60*60

reload_config = False

def main():
    global blocklist
    global allowlist
    global reload_config

    # open modem
    modem = Modem(modem_port, 1200)

    # reset modem
    modem.send_command("ATZ")
    
    # enable Caller ID
    modem.send_command("AT+VCID=1")

    # read allowlist
    print("Reading allow list file...")
    allowlist = read_list(allowlist_file)
    print("Allow List:")
    print_list(allowlist)
    update_list_match(allowlist, allowlist_file)

    # read blocklist
    print("Reading block list file...")
    blocklist = read_list(blocklist_file)
    print("Block list:")
    print_list(blocklist)
    update_list_match(blocklist, blocklist_file)

    # enable SIGHUP to relaod allow/block lists
    signal.signal(signal.SIGHUP, sighup_handler)

    blocklist_purge_time = 0.0
    last_ring = 0.0
    call_date = ""
    call_time = ""
    call_name = ""
    call_number = ""

    print("Waiting for call...")
    
    while True:
        # check blocklist purge date
        if time.time()-blocklist_purge_time > blocklist_purge_days * day_secs:
            blocklist_purge_time = time.time()
            purge_list(blocklist, blocklist_file, blocklist_lifetime_days)

        # wait for RING or rest of Caller ID
        line = modem.read_line()

        # check for SIGHUP to reload allow/block lists
        if reload_config:
            reload_config = False
            
            # read allowlist
            print("Reading allow list file...")
            allowlist = read_list(allowlist_file)
            print("Allow List:")
            print_list(allowlist)
            update_list_match(allowlist, allowlist_file)

            # read blocklist
            print("Reading block list file...")
            blocklist = read_list(blocklist_file)
            print("Block list:")
            print_list(blocklist)
            update_list_match(blocklist, blocklist_file)

        # look for RING and Caller ID
        if line.startswith("RING"):
            if time.monotonic()-last_ring > 7.0:
                print("New call...")
            last_ring = time.monotonic()
            if not call_date:
                continue
        elif line.startswith("DATE"):
            call_date = re.sub('^\w+\s*=\s*', '', line)
            continue
        elif line.startswith("TIME"):
            call_time = re.sub('^\w+\s*=\s*', '', line)
            continue
        elif line.startswith("NMBR"):
            call_number = re.sub('^\w+\s*=\s*', '', line)
            continue
        elif line.startswith("NAME"):
            call_name = re.sub('^\w+\s*=\s*', '', line)
            if not call_date:
                continue
        else:
            continue

        # caller ID is complete when NAME seen or RING after DATE
        print("Caller ID date=" + call_date + " time=" + call_time + " number=" + call_number + " name=" + call_name)

        # create timestamp
        timestamp = time.strftime('%Y') + "-" + call_date[0:2] + "-" + call_date[2:4] + " " + call_time[0:2] + ":" + call_time[2:4]
            
        # check for matches
        match = "no match"
        if match_list_both(allowlist, "allow", call_number, call_name, timestamp):
            match = "allow"
            # update allowlist match
            update_list_match(allowlist, allowlist_file)
        elif match_list_both(blocklist, "block", call_number, call_name, timestamp):
            match = "block"
            # update blocklist match
            update_list_match(blocklist, blocklist_file)

            # terminate call
            modem.terminate_call()
            print("Call terminated.")
        else:
            print("No list match")
            if (modem.wait_for_star()):
                print("User * key seen...")
                item = {}
                regex = call_number
                try:
                    item['regex'] = re.compile(regex, re.IGNORECASE)
                except re.error:
                    print("Invalid regular expression '" + regex + "'")
                    regex = ""
                if regex:
                    item['timestamp'] = time.strftime("%Y-%m-%d %H:%M")
                    item['count'] = 0
                    item['permanent'] = False
                    item['note'] = "added by user * key"
                    blocklist[regex] = item
                    with open(blocklist_file, 'a') as file:
                        line = regex + ";;added by user * key\n"
                        file.write(line)
                    print ("Added " + regex + " to block list")
                    match = "added to block by user * key"

        # log call
        with open(calllog_file, 'a') as file:
            line = timestamp + "  " + space_fill(call_number, 12) + space_fill(call_name, 17) + " : " + match + "\n"
            file.write(line)

        call_date = ""
        call_time = ""
        call_name = ""
        call_number = ""
        print("Waiting for call...")

    # close modem
    modem.send_command("ATH")
    modem.send_command("ATZ")
    modem.close()


def space_fill(s, count):
    return s + " " + (" " * (count-len(s)-1))
    
def read_list(list_file):
    # list is an dictionary of dictionaries, keyed on regex
    list = {}

    # process list
    if not os.path.exists(list_file):
        print("List file " + list_file + " not found")
        return list

    now = time.strftime("%Y-%m-%d %H:%M")
    with open(list_file) as file:
        for line in file:
            line = re.sub('\n|\r', '', line)
            if line.startswith("#"):
                continue
            line_list = line.split(";")
            # regex[;flags[;note]]
            regex = line_list.pop(0)
            if not regex:
                continue
            item = {}
            # regex may have a "\;" embedded in it
            while regex and regex.endswith("\\") and line_list:
                regex = regex[:-1]
                regex += ";" + line_list.pop(0)
            try:
                item['regex'] = re.compile(regex, re.IGNORECASE)
            except re.error:
                print("Invalid regular expression '" + regex + "', skipping entry")
                regex = ""
            if regex:
                item['regex'] = re.compile(regex, re.IGNORECASE)
                flags = line_list.pop(0) if line_list else ""
                item['permanent'] = 'p' in flags or 'P' in flags
                item['note'] = ";".join(line_list)
                item['timestamp'] = now
                item['count'] = 0
                list[regex] = item

    # process match history file for list
    match_file = list_file + "-match"
    if not os.path.exists(match_file):
        print("Match file " + match_file + " for list not found (OK)")
        return list

    with open(match_file) as file:
        for line in file:
            line = re.sub('\n|\r', '', line)
            line_list = line.split(";", 3)
            # timestamp;count;regex
            if len(line_list) == 3:
                timestamp = line_list.pop(0)
                count = line_list.pop(0)
                regex = line_list.pop(0)
                if regex in list:
                    list[regex]['timestamp'] = timestamp
                    list[regex]['count'] = int(count)
            else:
                print("Invalid line in match file: '" + line + "'")
                    
    return list

def update_list_match(list, list_file):
    match_file = list_file + "-match"
    with open(match_file, 'w') as file:
        for regex, item in list.items():
            line = item['timestamp'] + ";" + str(item['count']) + ";" + regex + "\n"
            file.write(line)

def match_list_both(list, list_type, number, name, timestamp):
    print("Checking " + list_type + " list...")
    if match_list(list, number, timestamp) or match_list(list, name, timestamp):
        print("Matched " + list_type + " list")
        return True
    return False

def match_list(list, string, timestamp):
    for regex, item in list.items():
        if item['regex'].match(string):
            item['timestamp'] = timestamp
            item['count'] += 1
            print("Matched pattern '" + regex + "' count " + str(item['count']))
            return True
    return False

def print_list(list):
    for key, item in list.items():
        print(key + " : " + str(item))

def purge_list(list, list_file, lifetime_days):
    if not os.path.exists(list_file):
        return

    print("Purging entries from " + list_file + " not matched in " + str(lifetime_days) + " days...")
    now = time.time()
    new_contents = ""
    file_changed = False
    with open(list_file) as file:
        for line in file:
            if not line.startswith("#"):
                line_list = re.sub('\n|\r', '', line).split(";")
                # regex[;flags[;note]]
                regex = line_list.pop(0)
                # regex may have a "\;" embedded in it
                while regex and regex.endswith("\\") and line_list:
                    regex = regex[:-1]
                    regex += ";" + line_list.pop(0)
                if regex in list:
                    item = list[regex]
                    print("Block item '" + regex + "' last blocked on " +
                          item['timestamp'] + " count " + str(item['count']))
                    last_time = time.mktime(time.strptime(item['timestamp'], "%Y-%m-%d %H:%M"))
                    if not item['permanent'] and now-last_time > lifetime_days * day_secs:
                        print("Removed '" + regex + "' from block list.")
                        print("    last blocked on " + item['timestamp'] + " count " + str(item['count']))
                        line = "# last blocked on " + item['timestamp'] + " count " + str(item['count']) + " #" + line
                        # remove from running list too
                        del list[regex]
                        file_changed = True
            new_contents += line

    if file_changed:
        # save existing file as backup
        backup_file = list_file + "-backup"
        if os.path.exists(backup_file):
            os.remove(backup_file)
        os.rename(list_file, backup_file)
        
        # write changed file
        with open(list_file, 'w') as file:
            file.write(new_contents)
    return


class Modem(serial.Serial):
    def __init__(self, port, baud):
        serial.Serial.__init__(self, port=port, baudrate=baud)

    def send_command(self, command, wait=True):
        self.reset_input_buffer()
        print("Send '" + command + "'")
        send_command = command + "\r"
        self.write(send_command.encode())
        if not wait:
            return True
        line = self.read_line()
        if line == command:
            line = self.read_line()
        return line == "OK"
    
    def read_line(self):
        line = ""
        while not line:
            line = re.sub('\n|\r', '', self.readline(200).decode())
        print("Received '" + line + "'")
        return line

    def wait_for_star(self):
        # wait up to 10 seconds for possible * key press to add to block list
        print("Waiting 10 seconds for user * key...")
        self.send_command("AT+FCLASS=8")        # voice mode
        self.send_command("AT+VIP")             # reset voice parameters
        self.send_command("AT+VLS=4")           # mode 4 - stay on-hook
        self.timeout = 1.0
        star_bytes = b'\x10/\x10*\x10~'         # <DLE>/<DLE>*<DLE>~ - DTMF *
        ring_bytes1 = b'\x10R'                  # <DLE>R - ring voltage
        ring_bytes2 = b'\x10r'                  # <DLE>r - ring tone
        read_bytes = b''
        last_ring = time.monotonic()
        while time.monotonic()-last_ring < 10.0 and not star_bytes in read_bytes:
            read_bytes += self.read(1)
            if b'\n' in read_bytes:
                # must re-init voice mode afer ring and \r\n
                self.send_command("AT+VIP")
                self.send_command("AT+VLS=4")
                read_bytes = b''
            if ring_bytes1 in read_bytes or ring_bytes2 in read_bytes:
                print("Ring...")
                read_bytes = read_bytes.replace(ring_bytes1, b'')
                read_bytes = read_bytes.replace(ring_bytes2, b'')
                last_ring = time.monotonic()
        print("Read " + str(len(read_bytes)) + " bytes " + str(read_bytes))
        self.timeout = None
        self.send_command("ATH")                # hang up modem (should not be off hook)
        return star_bytes in read_bytes

    def terminate_call(self):
        self.send_command("AT+FCLASS=1")        # fax mode
        self.send_command("ATA", False)         # answer like a fax but don't wait
        time.sleep(2)
        self.send_command("ATH")                # hang up fax call
        time.sleep(1)
        self.send_command("ATH")                # hang up modem

def sighup_handler(signum, frame):
    global reload_config
    print("SIGHUP received - reloading allow/block lists on next call")
    reload_config = True

main()
