#!/usr/bin/env python
import moveit_commander

import rospy

import actionlib

import amazon_challenge_bt_actions.msg

from std_msgs.msg import String
import sys

import tf
import PyKDL as kdl
import pr2_moveit_utils.pr2_moveit_utils as pr2_moveit_utils
from pr2_controllers_msgs.msg import Pr2GripperCommand
from geometry_msgs.msg import Pose, PoseStamped
from tf_conversions import posemath
import math
from calibrateBase import baseMove
from amazon_challenge_motion.bt_motion import BTMotion
import amazon_challenge_bt_actions.msg
from grasping.generate_object_dict import *


class BTAction(object):
    # create messages that are used to publish feedback/result
    _feedback = amazon_challenge_bt_actions.msg.BTFeedback()
    _result = amazon_challenge_bt_actions.msg.BTResult()

    def __init__(self, name):
        self._action_name = name
        self._as = actionlib.SimpleActionServer(self._action_name, amazon_challenge_bt_actions.msg.BTAction,
                                                execute_cb=self.execute_cb, auto_start=False)
        self._as.start()
        self.pub_grasped = rospy.Publisher('object_grasped', String)
        self.pub_pose = rospy.Publisher('hand_pose', PoseStamped)
        self.pub_rate = rospy.Rate(30)
        while not rospy.is_shutdown():
            try:
                self.left_arm = moveit_commander.MoveGroupCommander('left_arm')
                # self.left_arm.set_planning_time(1.0)
                self.right_arm = moveit_commander.MoveGroupCommander('right_arm')
                # self.right_arm.set_planning_time(1.0)
                break
            except:
                pass


        self.listener = tf.TransformListener()
        moveit_commander.roscpp_initialize(sys.argv)
        rospy.Subscriber("/amazon_next_task", String, self.get_task)
        self._item = ""
        self._bin = ""
        self.l_gripper_pub = rospy.Publisher('/l_gripper_controller/command', Pr2GripperCommand)
        self.r_gripper_pub = rospy.Publisher('/r_gripper_controller/command', Pr2GripperCommand)
        

        self.grasping_param_dict = rospy.get_param('/grasping_param_dict')
        self.pre_distance = self.grasping_param_dict['pre_distance'] # should get from grasping_dict
        self.ft_switch = self.grasping_param_dict['ft_switch']
        self.lifting_height = self.grasping_param_dict['lifting_height']
        self.topGraspHeight = self.grasping_param_dict['topGraspHeight']
        self.topGraspingFrame = self.grasping_param_dict['topGraspingFrame']
        self.sideGraspingTrialAngles = self.grasping_param_dict['sideGraspingTrialAngles']
        self.sideGraspingTolerance = self.grasping_param_dict['sideGraspingTolerance']
        self.base_retreat_distance = self.grasping_param_dict['base_retreat_distance']
        self.topGraspingTrials = self.grasping_param_dict['topGraspingTrials']
        self.sideGraspingTrials = self.grasping_param_dict['sideGraspingTrials']
        self.gripperWidth = self.grasping_param_dict['gripperWidth']
        self.topGraspingPitch = self.grasping_param_dict['topGraspingPitch']
        self.topGraspingRoll = self.grasping_param_dict['topGraspingRoll']
        self.dictObj = objDict()
        self.objSpec = {}
        self.topGrasping_pre_distance = self.grasping_param_dict['topGrasping_pre_distance']
        # base movement
        self._bm = baseMove.baseMove(verbose=False)
        self._bm.setPosTolerance(0.02)
        self._bm.setAngTolerance(0.006)
        self._bm.setLinearGain(0.4)
        self._bm.setAngularGain(1)

        self._tool_size = rospy.get_param('/tool_size', [0.16, 0.02, 0.04])
        rospy.loginfo('Grapsing action ready')

    def flush(self):
        self._item = ""
        self._bin = ""
        self.objSpec = {}

    def transformPoseToRobotFrame(self, planPose, planner_frame):

        pre_pose_stamped = PoseStamped()
        pre_pose_stamped.pose = posemath.toMsg(planPose)
        pre_pose_stamped.header.stamp = rospy.Time()
        pre_pose_stamped.header.frame_id = planner_frame

        while not rospy.is_shutdown():
            try:
                robotPose = self.listener.transformPose('/base_link', pre_pose_stamped)
                break
            except:
                pass

        self.pub_pose.publish(robotPose)
        return robotPose


    def RPYFromQuaternion(self, q):
        return tf.transformations.euler_from_quaternion([q[0], q[1], q[2], q[3]])




    def execute_cb(self, goal):
        # publish info to the console for the user
        rospy.loginfo('Starting Grasping')
        try:
            self.objSpec = self.dictObj.getEntry(self._item)
        except Exception, e:
            print e
            self.set_status('FAILURE')
            return

            self.pre_distance = self.objSpec.pre_distance # this is decided upon per object
        # start executing the action
        # check that preempt has not been requested by the client
        if self._as.is_preempt_requested():
            rospy.loginfo('Action Halted')
            self._as.set_preempted()
            return

        rospy.loginfo('Executing Grasping')
        status = False
        for gs in self.objSpec.graspStrategy:
            if gs == 0:
                rospy.loginfo("sideGrasping is chosen")
                for i in range(self.sideGraspingTrials):
                    status = self.sideGrasping()
                    if status:
                        break
                if status:
                    break
            elif gs == 1:
                rospy.loginfo("topGrasping is chosen")
                for i in range(self.topGraspingTrials):
                    status = self.topGrasping()
                    if status:
                        break
                if status:
                    break
            else:
                self.flush()
                rospy.logerr('No strategy found to grasp')
                self.set_status('FAILURE')

        if status:
            self.set_status('SUCCESS')
        else:
            self.set_status('FAILURE')
        return


    def topGrasping(self):

        row_height = self.grasping_param_dict['row_height'][self.get_row()]

        while not rospy.is_shutdown():
            try:
                tp = self.listener.lookupTransform('/base_link', "/" + self._item + "_detector", rospy.Time(0))
                rospy.loginfo('got new object pose')
                tpRPY = self.RPYFromQuaternion(tp[1])
                break
            except:
                pass

        self.open_left_gripper()



        tool_frame_rotation = kdl.Rotation.RPY(math.radians(self.topGraspingRoll), math.radians(self.topGraspingPitch), 0)
        '''
        PRE-GRASPING
        '''

        pre_pose = kdl.Frame(tool_frame_rotation, kdl.Vector( tp[0][0] + self.topGrasping_pre_distance, tp[0][1], tp[0][2] + self.topGraspHeight))


        try:
            pr2_moveit_utils.go_tool_frame(self.left_arm, pre_pose, base_frame_id = self.topGraspingFrame, ft=self.ft_switch,
                                           wait=True, tool_x_offset=self._tool_size[0])
        except:
            self.flush()
            rospy.logerr('exception in PRE-GRASPING')
            return False


        '''
        REACHING
        '''

        reaching_pose = kdl.Frame(tool_frame_rotation, kdl.Vector( tp[0][0], tp[0][1], tp[0][2] + self.topGraspHeight))

       
        try:
            pr2_moveit_utils.go_tool_frame(self.left_arm, reaching_pose, base_frame_id = self.topGraspingFrame, ft=self.ft_switch,
                                           wait=True, tool_x_offset=self._tool_size[0])
        except:
            self.flush()
            rospy.logerr('exception in REACHING')
            return False

        '''
        TOUCHING
        '''

        touching_height = max(tp[0][2], row_height)
        touching_pose = kdl.Frame(tool_frame_rotation, kdl.Vector( tp[0][0], tp[0][1], touching_height))
        rospy.logerr("touching_height: %4f" % touching_height)
        
        try:
            pr2_moveit_utils.go_tool_frame(self.left_arm, touching_pose, base_frame_id = self.topGraspingFrame, ft=self.ft_switch,
                                           wait=True, tool_x_offset=self._tool_size[0])
        except:
            self.flush()
            rospy.logerr('exception in TOUCHING')
            return False

        '''
        GRASPING
        '''

        self.close_left_gripper()

        '''
        LIFTING
        '''

        lifting_pose = kdl.Frame(tool_frame_rotation, kdl.Vector( tp[0][0], tp[0][1], tp[0][2] + self.topGraspHeight))
        


        try:
            pr2_moveit_utils.go_tool_frame(self.left_arm, lifting_pose, base_frame_id = self.topGraspingFrame, ft=self.ft_switch,
                                           wait=True, tool_x_offset=self._tool_size[0])
        except:
            self.flush()
            self.open_left_gripper()
            rospy.logerr('exception in LIFTING')
            return False

        '''
        RETREATING
        '''
        rospy.loginfo('RETREATING')

        try:
            base_pos_dict = rospy.get_param('/base_pos_dict')
            column = self.get_column()
            base_pos_goal = base_pos_dict[column]
            base_pos_goal[0] -= abs(self.base_retreat_distance)
            self.go_base_pos_async(base_pos_goal)
        except Exception, e:
            rospy.logerr(e)
            self.flush()

            self.open_left_gripper()

            rospy.logerr('exception in RETREATING')
            return False



        return True

    def sideGrasping(self):

        while not rospy.is_shutdown():
            try:
                tp = self.listener.lookupTransform('/base_link', "/" + self._item + "_detector", rospy.Time(0))
                binFrame = self.listener.lookupTransform("/" + "shelf_" + self._bin, "/" + self._item + "_detector", rospy.Time(0))
                liftShift = 0.15 - binFrame[0][1]
                rospy.loginfo('got new object pose')
                tpRPY = self.RPYFromQuaternion(tp[1])
                objBinRPY = self.RPYFromQuaternion(binFrame[1])
                break
            except:
                pass


        if abs(objBinRPY[1]) > 0.5:
            rospy.logerr('require pushing the object')
            return False

        angle_step = 0

        if objBinRPY[2] < 0:
            angle_step = -self.sideGraspingTolerance / (self.sideGraspingTrialAngles - 1.0)
        else:
            angle_step = self.sideGraspingTolerance / (self.sideGraspingTrialAngles - 1.0)


        for i in range(self.sideGraspingTrialAngles):

            yaw_now = angle_step * i
            y_shift_now = self.gripperWidth / 2. * (1. - math.cos(yaw_now))
            rospy.loginfo('yaw_now: %4f, y_shift_now: %4f' % (yaw_now, y_shift_now))
            x_shift_now = y_shift_now * math.tan(y_shift_now)
            '''
            PRE-GRASPING
            '''
            rospy.loginfo('PRE-GRASPING')
            planner_frame = '/' + self._item + "_detector"

            self.open_left_gripper()

            rospy.logerr(yaw_now)
            pre_pose = kdl.Frame(kdl.Rotation.RPY(0, 0, yaw_now), kdl.Vector( self.pre_distance - x_shift_now, -y_shift_now, 0))
            pre_pose_robot = self.transformPoseToRobotFrame(pre_pose, planner_frame)

            
            try:
                pr2_moveit_utils.go_tool_frame(self.left_arm, pre_pose_robot.pose, base_frame_id = pre_pose_robot.header.frame_id, ft=self.ft_switch,
                                               wait=True, tool_x_offset=self._tool_size[0])
            except Exception, e:
                rospy.logerr('exception in PRE-GRASPING')
                rospy.logerr(e)
                continue

            '''
            REACHING
            '''
            rospy.loginfo('REACHING')
            reaching_pose = kdl.Frame(kdl.Rotation.RPY(0, 0, yaw_now), kdl.Vector( 0.0,y_shift_now,0))
            reaching_pose_robot = self.transformPoseToRobotFrame(reaching_pose, planner_frame)

        
            try:
                pr2_moveit_utils.go_tool_frame(self.left_arm, reaching_pose_robot.pose, base_frame_id = reaching_pose_robot.header.frame_id, ft=self.ft_switch,
                                               wait=True, tool_x_offset=self._tool_size[0])
            except:
                rospy.logerr('exception in REACHING')
                continue

            '''
            GRASPING
            '''
            rospy.loginfo('GRASPING')
            self.close_left_gripper()
            '''
            LIFTING
            '''

            rospy.loginfo('LIFTING')

            lifting_pose = kdl.Frame(kdl.Rotation.RPY(tpRPY[0], tpRPY[1], 0), kdl.Vector( tp[0][0], tp[0][1] + liftShift, tp[0][2] + self.lifting_height))

        
            try:
                pr2_moveit_utils.go_tool_frame(self.left_arm, lifting_pose, base_frame_id = 'base_link', ft=self.ft_switch,
                                               wait=True, tool_x_offset=self._tool_size[0])
            except:
                self.open_left_gripper()
                rospy.logerr('exception in LIFTING')
                continue

            '''
            RETREATING
            '''
            rospy.loginfo('RETREATING')
            # retreating_pose = kdl.Frame(kdl.Rotation.RPY(tpRPY[0], tpRPY[1], tpRPY[2]), kdl.Vector( tp[0][0] - self.retreat_distance, tp[0][1], tp[0][2]))

        
            # try:
            #     pr2_moveit_utils.go_tool_frame(self.left_arm, retreating_pose, base_frame_id = 'base_link', ft=self.ft_switch,
            #                                    wait=True, tool_x_offset=self._tool_size[0])
            # except:
            #     self.flush()
            #     rospy.logerr('exception in RETREATING')
            #     self.set_status('FAILURE')
            #     return

            try:
                base_pos_dict = rospy.get_param('/base_pos_dict')
                column = self.get_column()
                base_pos_goal = base_pos_dict[column]
                base_pos_goal[0] -= abs(self.base_retreat_distance)
                self.go_base_pos_async(base_pos_goal)
            except Exception, e:
                rospy.logerr(e)
                self.flush()

                self.open_left_gripper()

                rospy.logerr('exception in RETREATING')
                continue

            rospy.loginfo('Grasping successful')
            self.flush()
            return True



        #IF THE ACTION HAS FAILED
        self.flush()
        return False


    def set_status(self, status):
        if status == 'SUCCESS':
            self._feedback.status = 1
            self._result.status = self._feedback.status
            rospy.loginfo('Action %s: Succeeded' % self._action_name)
            self._as.set_succeeded(self._result)
        elif status == 'FAILURE':
            self._feedback.status = 2
            self._result.status = self._feedback.status
            rospy.loginfo('Action %s: Failed' % self._action_name)
            self._as.set_succeeded(self._result)
        else:
            rospy.logerr('Action %s: has a wrong return status' % self._action_name)

    def get_task(self, msg):
        text = msg.data
        text = text.replace('[','')
        text = text.replace(']','')
        words = text.split(',')
        self._bin = words[0]
        self._item = words[1]


    def go_left_gripper(self, position, max_effort):
        """Move left gripper to position with max_effort
        """
        ope = Pr2GripperCommand()
        ope.position = position
        ope.max_effort = max_effort
        self.l_gripper_pub.publish(ope)

    def go_right_gripper(self, position, max_effort):
        """Move right gripper to position with max_effort
        """
        ope = Pr2GripperCommand()
        ope.position = position
        ope.max_effort = max_effort
        self.r_gripper_pub.publish(ope)

    def close_left_gripper(self):
        self.go_left_gripper(0, 40)
        rospy.sleep(4)

    def close_right_gripper(self):
        self.go_right_gripper(0, 40)
        rospy.sleep(4)

    def open_left_gripper(self):
        self.go_left_gripper(10, 40)
        rospy.sleep(2)

    def open_right_gripper(self):
        self.go_right_gripper(10, 40)
        rospy.sleep(2)

    def go_base_pos_async(self, base_pos_goal):

        angle = base_pos_goal[5]
        pos = base_pos_goal[0:2]
        r = rospy.Rate(100.0)

        # check for preemption while the base hasn't reach goal configuration
        while not self._bm.goAngle(angle) and not rospy.is_shutdown():

            # check that preempt has not been requested by the client
            if self._as.is_preempt_requested():
                #HERE THE CODE TO EXECUTE WHEN THE  BEHAVIOR TREE DOES HALT THE ACTION
                group.stop()
                rospy.loginfo('[pregrasp_server]: action halted while moving base')
                self._as.set_preempted()
                self._success = False
                return False

            #HERE THE CODE TO EXECUTE AS LONG AS THE BEHAVIOR TREE DOES NOT HALT THE ACTION
            r.sleep()

        while not self._bm.goPosition(pos) and not rospy.is_shutdown():

            # check that preempt has not been requested by the client
            if self._as.is_preempt_requested():
                #HERE THE CODE TO EXECUTE WHEN THE  BEHAVIOR TREE DOES HALT THE ACTION
                group.stop()
                rospy.loginfo('[pregrasp_server]: action halted while moving base')
                self._as.set_preempted()
                self._success = False
                return False

            #HERE THE CODE TO EXECUTE AS LONG AS THE BEHAVIOR TREE DOES NOT HALT THE ACTION
            r.sleep()

        while not self._bm.goAngle(angle) and not rospy.is_shutdown():

            # check that preempt has not been requested by the client
            if self._as.is_preempt_requested():
                #HERE THE CODE TO EXECUTE WHEN THE  BEHAVIOR TREE DOES HALT THE ACTION
                group.stop()
                rospy.loginfo('[pregrasp_server]: action halted while moving base')
                self._as.set_preempted()
                self._success = False
                return False

            #HERE THE CODE TO EXECUTE AS LONG AS THE BEHAVIOR TREE DOES NOT HALT THE ACTION
            r.sleep()

        return True

    def get_column(self):
        '''
        For setting the base pose
        '''
        while not rospy.is_shutdown():
            try:
                if self._bin=='bin_A' or self._bin=='bin_D' or self._bin=='bin_G' or self._bin=='bin_J':
                    return 'column_1'

                elif self._bin=='bin_B' or self._bin=='bin_E' or self._bin=='bin_H' or self._bin=='bin_K':
                    return 'column_2'

                elif self._bin=='bin_C' or self._bin=='bin_F' or self._bin=='bin_I' or self._bin=='bin_L':
                    return 'column_3'

            except:
                pass

    def get_row(self):
        while not rospy.is_shutdown():
            try:
                if self._bin=='bin_A' or self._bin=='bin_B' or self._bin=='bin_C':
                    return 'row_1'

                elif self._bin=='bin_D' or self._bin=='bin_E' or self._bin=='bin_F':
                    return 'row_2'

                elif self._bin=='bin_G' or self._bin=='bin_H' or self._bin=='bin_I':
                    return 'row_3'

               
                elif self._bin=='bin_J' or self._bin=='bin_K' or self._bin=='bin_L':
                    return 'row_4'
            except:
                pass




if __name__ == '__main__':
    rospy.init_node('grasp_object')
    BTAction(rospy.get_name())
    rospy.spin()
