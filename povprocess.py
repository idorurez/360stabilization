#!/usr/bin/env python
# -*- coding: latin-1 -*--

from __future__ import division
import unittest
import jaunt.framework.app
import jaunt.logging
import sys
import os
import datetime
import time
import math
from collections import OrderedDict

DATALOGFORMAT = "%s %s,%s,%s,%s,%s\n"
DATEFORMAT = "%Y-%m-%d"
TIMEFORMAT = "%H:%M:%S.%f"
DATETIMEFORMAT = DATEFORMAT + " " + TIMEFORMAT
TABLEHEADING = "Date Time,Frame,Heading,Pitch,Roll\n"

class App(jaunt.framework.app.App):

    def __init__(self):

        self.fps = 60
        self.fileIn = None
        self.fileOut = 'povprocess.txt'

        self.readings = OrderedDict()
        self.readingsList = None
        self.readingsTimestamps = None
        self.sampledReadings = OrderedDict()
        self.refDate = datetime.datetime(1970, 1, 1)
        self.utcoffset = datetime.timedelta(hours = 0)

    def preflight(self, *args, **kwargs):
        """ Check for proper environment configuration. """
        super(App, self).preflight(*args, **kwargs)

    def configureParser(self, prog, *args, **kwargs):
        """ Configure the argparse self.parser object.
            See: https://docs.python.org/2/library/argparse.html
        """
        super(App, self).configureParser(prog, *args, **kwargs)
        self.parser.add_argument('-exr', '--exr', action='store_true', help="Publish exrs")
        self.parser.add_argument('-skip', '--skip', action='store_true', help="Skip confirmation of Publish")

        self.parser.add_argument('-i', '--in', help="Input file")
        self.parser.add_argument('-o', '--out', help="Output file. Default povprocess.txt")

        self.parser.add_argument('-f', '--fps', help="Sampling rate, default is 30 fps")



    def validateNamespace(self, prog, *args, **kwargs):
        """ Configure the self.namespace object generated by argparse.
            Raise exceptions, for example, for complex mutual-exclusion
            requirements.  Add new attributes to the object based on
            collections of parsed arguments. """

        super(App, self).validateNamespace(None, *args, **kwargs)


        if self.namespace['fps']:
            self.fps = float(self.namespace['fps'])
        if not (isinstance(self.fps, int) or (isinstance(self.fps, float))):
            print "Please specify a valid fps sampling rate"

        self.fileIn = self.namespace['in']
        if not self.fileIn:
            print "Missing input file. Please specify with -i"
            sys.exit(1)
        else:
            if not os.path.isfile(self.fileIn):
                print "Input file does not exist. Please confirm that the file and path exists"
                sys.exit(1)

        if self.namespace['out']:
            self.fileOut = self.namespace['out']
        if not self.fileOut:
            print "Please specify a valid file output"

    def ingestData(self, file):

        try:
            with open(file) as f:
                for line in f:
                    line = line.split()
                    if len(line) < 6:
                        continue    # the line is short of what we need
                    dateInf = line[0]
                    timeInf = line[1]
                    # index = line[2]
                    heading = line[3].split("=")[1]
                    roll = line[4].split("=")[1]
                    pitch = line[5].split("=")[1]

                    timeindex = datetime.datetime.strptime("{} {}".format(str(dateInf), str(timeInf)), DATETIMEFORMAT)

                    timeindex = timeindex - self.refDate

                    timeindex = timeindex.total_seconds() + (1/timeindex.microseconds)

                    # timeindex = "{:.20f}".format(timeindex)

                    indexedVals = {}
                    indexedVals["date"] = dateInf
                    indexedVals["time"] = timeInf
                    indexedVals["heading"] = float(heading)
                    indexedVals["roll"] = float(roll)
                    indexedVals["pitch"] = float(pitch)

                    self.readings[timeindex] = indexedVals

            # get list so we can grab first val
            # also get list of time stamps
            self.readingsList = list(self.readings.items())
            self.readingsTimestamps = self.readings.keys()

        except IOError as e:
            print ("Unable to open " + file + ", " + str(e))
            sys.exit(1)
        except ValueError as e:
            print ("Unable to parse file: " + str(e))
            sys.exit(1)

    def process(self, file):
        vals = {}
        samples = self.totalSamples()
        frame = 1
        print "There will be a total of " + str(samples) + " samples"

        try:
            f = open(file, "w+")
        except IOError as e:
            print "Unable to open file, " + e
            sys.exit(1)

        # Grab and write the first set of values
        vals['date'] = self.readingsList[0][1]['date']
        vals['time'] = self.readingsList[0][1]['time']
        vals['heading'] = self.readingsList[0][1]['heading']
        vals['pitch'] = self.readingsList[0][1]['pitch']
        vals['roll'] = self.readingsList[0][1]['roll']
        vals['frame'] = frame

        self.writeVals(f, TABLEHEADING, None)
        self.writeVals(f, DATALOGFORMAT, vals)

        # get the timedelta, since I don't know what timezone the reading is from, and datetime will assume UTC when converting
        fdate = datetime.datetime.fromtimestamp(self.readingsList[1][0])
        pdate = datetime.datetime.strptime("{} {}".format(str(vals['date']), str(vals['time'])), DATETIMEFORMAT)
        self.utcoffset = pdate - fdate

        readingsIndex = 1                                           # initial readingslist sample
        sampleTime = self.readingsList[0][0] + 1/self.fps           # initial time we want to sample

        for x in range(samples):
            while readingsIndex+1 <= len(self.readingsList):

                if (self.readingsList[readingsIndex-1][0] < sampleTime) and (sampleTime < self.readingsList[readingsIndex][0]):
                    # print "TRUE!!! {:.20f} < {:.20f} <= {:.20f}".format(self.readingsList[readingsIndex-1][0], sampleTime, self.readingsList[readingsIndex][0])
                    frame += 1
                    vals = self.interpSamples(sampleTime, readingsIndex-1, readingsIndex)
                    vals['frame'] = frame
                    self.writeVals(f, DATALOGFORMAT, vals)
                    sampleTime += 1/self.fps
                else:
                    # print "{:.20f} < {:.20f} <= {:.20f}".format(self.readingsList[readingsIndex-1][0], sampleTime, self.readingsList[readingsIndex][0])
                    # Move the index up until the sample time falls in between
                    readingsIndex += 1


    def interpSamples(self, time_i, index0, index1):
        vals = {}

        reading0 = self.readingsList[index0]
        reading1 = self.readingsList[index1]

        time_0 = float(reading0[0])
        time_1 = float(reading1[0])

        # add the utc offset, if any
        dt = datetime.datetime.fromtimestamp(time_i) + self.utcoffset

        vals['date'] = dt.strftime(DATEFORMAT)
        vals['time'] = dt.strftime(TIMEFORMAT)
        vals['heading'] = self.interpVals(time_0, time_1, time_i, reading0[1]['heading'], reading1[1]['heading'])
        vals['pitch'] = self.interpVals(time_0, time_1, time_i, reading0[1]['pitch'], reading1[1]['pitch'])
        # print ("PITCH INTERP IS WITH: {:.5f}, {:.5f}, {:.5f}, {}, {} = {}".format(time_0, time_i, time_1, reading0[1]['pitch'], reading1[1]['pitch'], vals['pitch']))

        vals['roll'] = self.interpVals(time_0, time_1, time_i, reading0[1]['roll'], reading1[1]['roll'])

        return vals

    def interpVals(self, time_0, time_1, time_i, val_0, val_1):
        interpVal = val_0 + ((val_1 - val_0) * ((time_i - time_0) / (time_1 - time_0)))

        return interpVal

    def writeVals(self, f, format, vals):

        entry = format

        if vals:
            entry = format % (str(vals['date']),
                                     str(vals['time']),
                                     str(vals['frame']),
                                     str(vals['heading']),
                                     str(vals['pitch']),
                                     str(vals['roll']))

        f.write(entry)

    def totalSamples(self):
        fReading = self.readingsList[0]
        lReading = self.readingsList[-1]

        totalTimeSeconds = lReading[0] - fReading[0]

        totalSamples = int(totalTimeSeconds * self.fps) # gives floor with int

        return totalSamples

    def run(self, *args, **kwargs):
        super(App, self).run(*args, **kwargs)
        """ Main app code goes here. """

        print "Ingesting data..."
        self.ingestData(self.fileIn)

        print "Processing data and writing out..."
        self.process(self.fileOut)
        print "Done!"

        sys.exit(0)



class TestApp(unittest.TestCase):
    def setUp(self):
        """ Work to do before each test. """
        self.app = App()

    def tearDown(self):
        """ Work to do after each test. """
        pass

    def testRun(self):
        """ Run a test of the whole app. """
        assert self.app is not None

    def testFoo(self):
        """ Run a test called "Foo" """
        assert False == True

if __name__ == "__main__":
    import sys
    if "--runtests" in sys.argv:
        unittest.main()
    else:
        App().run()

