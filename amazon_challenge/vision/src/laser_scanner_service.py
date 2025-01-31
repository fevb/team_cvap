#!/usr/bin/env python

PKG = "pr2_mechanism_controllers"

import roslib; roslib.load_manifest(PKG) 

import sys
import os
import string

import rospy
from std_msgs import *

from pr2_msgs.msg import LaserTrajCmd
from pr2_msgs.srv import *
from time import sleep


cmd = LaserTrajCmd()
controller   =    'laser_tilt_controller'
cmd.header   =    rospy.Header(None, None, None)
cmd.profile  = "blended_linear"
#cmd.pos      = [1.0, .26, -.26, -.7,   -.7,   -.26,   .26,   1.0, 1.0]
d = .025
#cmd.time     = [0.0, 0.4,  1.0, 1.1, 1.1+d,  1.2+d, 1.8+d, 2.2+d, 2.2+2*d]

dur = 15;
cmd.position = [-1.0,  0, 1]
cmd.time_from_start = [0.0, dur, dur+1]
cmd.time_from_start = [rospy.Duration.from_sec(x) for x in cmd.time_from_start]
cmd.max_velocity = 10
cmd.max_acceleration = 30

print 'Sending Command to %s: ' % controller
print '  Profile Type: %s' % cmd.profile
print '  Pos: %s ' % ','.join(['%.3f' % x for x in cmd.position])
print '  Time: %s' % ','.join(['%.3f' % x.to_sec() for x in cmd.time_from_start])
print '  MaxRate: %f' % cmd.max_velocity
print '  MaxAccel: %f' % cmd.max_acceleration

rospy.wait_for_service(controller + '/set_traj_cmd')                                        
s = rospy.ServiceProxy(controller + '/set_traj_cmd', SetLaserTrajCmd)
resp = s.call(SetLaserTrajCmdRequest(cmd))

print 'Command sent!'
print '  Resposne: %f' % resp.start_time.to_sec()