# jcblock.py - block junk (unwanted) calls

## History

This is a port of jcblock.c by Walter S. Heath (2018).

The junk calls on my landline had greatly increased during The Pandemic.  Our
Panasonic cordless phone does a good job of blocking specific numbers, so this
was fine.  But I realized I needed a junk call blocker that could identify
patterns in the Caller ID Name.

I have two Raspberry Pis running stuff in my house, so I thought I should look
for a solution that would run on a Pi.  I found jcblock.c
(https://sourceforge.net/projects/jcblock/) which did what I want but only
offered simple string matching.

Rather than attempt to graft libpcre onto jcblock.c, I decided to re-implement
the functionality in Python.  This is the result.  After I wrote this, I found
another Python implementation in callblock.c
(https://github.com/dmeekins/callblock) which is similar but without
pattern-matching.

## Features

* Uses a USB AT Modem (Hayes Command Set).
  I have a Sewell USB modem.  YMMV (Your Modem May Vary).
* 'block' list specifies which number or name patterns to block
* 'allow' list specifies number or name patterns to always allow.
  This is checked before the 'block' list
* 'allow' and 'block' patterns are Regular Expressions (PCRE syntax).
  These patterns are applied to both the Name and Number Caller ID fields and
  are case-insensitive
* A Call Log is kept of all incoming calls and their disposition
* 'block' entries will be purged from the 'block' list after 9 months of not
  blocking any calls.  'block' entries can be marked as "Permanant" and will
  not be purged.
  A record of the last call for each pattern is kept separately from the lists
* Calls are blocked by answering the phone and immediately hanging up after
  the first ring
* Calls not marked for 'block' or 'allow' can be added to the 'block' list by
  answering the call and pressing the "*" key within 10 seconds

## Configuration

* 'allow' list : `allowlist.dat`
* 'block' list : `blocklist.dat`
* allow/block list file format:
```
        # <comment line>
        <pattern>;<flags>;<comment>
    <flags>: p -> entry will never be purged
    note: <pattern> includes any surrounding whitespace so ";" should
          immediately follow <pattern>.
          ";" can be included in <pattern> with "\;"
    examples:
        # this is a comment
        ^\w+\s+\w\w$;  p  ;this is <city> <st>, permanent
        978.....00; ;block all 978 area code numbers ending in 00
```
* Call log : `calllog.log`
* Static configuration (modem port, purge time, file names, etc.) are at the
  start of jcblock.py

## Authors

* Walter S. Heath (original jcblock.c)
* Tom Porcher (porcher@acm.org)
