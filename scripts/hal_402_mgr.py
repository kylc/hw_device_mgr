import rospy
import hal
import time
# import service messages from the ROS node
from hal_402_device_mgr.srv import srv_robot_state
from hal_402_drive import drive_402 as drive_402
from hal_402_drive import state_machine_402 as state_402


class hal_402_mgr(object):

    def __init__(self):
        self.compname = 'hal_402_mgr'
        self.drives = dict()
        self.prev_robot_state = 'unknown'
        self.curr_robot_state = 'unknown'
        # very simple transitions for now
        # unknown -> stopped
        # error -> stopped
        # stopped -> error
        # stopped -> started
        # started -> error
        self.states = {
            'unknown':  [state_402.path_to_switch_on_disabled, 'SWITCH ON DISABLED'],
            'started':  [state_402.path_to_operation_enabled, 'OPERATION ENABLED'],
            'stopped':  [state_402.path_to_switch_on_disabled, 'SWITCH ON DISABLED'],
            'error':    [state_402.path_to_switch_on_disabled, 'SWITCH ON DISABLED']
        }

        # create ROS node
        rospy.init_node(self.compname)
        rospy.loginfo("%s: Node started" % self.compname)

        # create HAL userland component
        self.halcomp = hal.component(self.compname)
        rospy.loginfo("%s: HAL component created" % self.compname)

        # create drives which create pins
        self.create_drives()
        self.halcomp.ready()

        # for testing and debug purpose
        self.sim_set_drivestates('FAULT')
        self.sim_set_drive_sim(True)

        self.create_service()
        self.create_publisher()

    def create_drives(self):
        for i in range(0, 6):
            # create 6 drives, later do this from ROS parameters
            drivename = "drive_%s" % (i + 1)
            self.drives[drivename] = drive_402(drivename, self)
            rospy.loginfo("%s: %s created" % (self.compname, drivename))

    def create_publisher(self):
        # todo, read from ROS param server
        self.update_rate = 1  # Hz
        self.rate = rospy.Rate(self.update_rate)
        # create publishers for topics and send out a test message
        for key, drive in self.drives.items():
            drive.create_topics()
            if (drive.sim is True):
                drive.test_publisher()

    def all_equal_status(self, status):
        # check if all the drives have the same status
        for key, drive in self.drives.items():
            if not (drive.curr_state == status):
                return False
        return True

    def sim_set_drive_sim(self, status):
        # set simulation attribute to mimic hanging statusword
        for key, drive in self.drives.items():
            drive.sim = True

    def sim_set_drivestates(self, status):
        for key, drive in self.drives.items():
            drive.sim_set_input_status_pins(status)
        # give HAL at least 1 cycle to process
        time.sleep(0.002)
        self.inspect_hal_pins()

    def cb_robot_state_service(self, req):
        # The service callback
        # the value of the requested state is in req.req_state (string)
        # the return value is the service response (string)
        # check the requested state for validity
        if req.req_state not in self.states:
            rospy.loginfo("%s: request for state failed, %s not a valid state" %
                          (self.compname,
                           req.req_state))
            return "request for state %s failed, state not known" % req.req_state
        # pick a transition table for the requested state
        tr_table = self.states[req.req_state][0]
        all_target_states = self.states[req.req_state][1]
        # set "active" transition table for the drive
        for key, drive in self.drives.items():
            drive.set_transition_table(tr_table)

        # the drive returns success if all the drives are :
        # OPERATION ENABLED or SWITCH ON DISABLED or max_attempts
        i = 0
        max_attempts = len(state_402.states_402)
        while ((not self.all_equal_status(all_target_states))
               or not (i in range(0, max_attempts))):
            for key, drive in self.drives.items():
                # traverse states for all drives (parallel)
                # ignore drives which state already is at the target state
                if not (drive.curr_state == all_target_states):
                    drive.next_transition()
            self.inspect_hal_pins()
            self.publish_states()
            i += 1

        # when states are successfully reached, update overall state
        # when all statuses have been reached, success
        # otherwise num_states has overflowed
        if self.all_equal_status(all_target_states):
            self.curr_robot_state = req.req_state
        else:
            self.curr_robot_state = 'error'
        return self.curr_robot_state

    def cb_test_service_cb(self, req):
        rospy.loginfo("%s: cb_test_service" % self.compname)
        # the response that's returned is the return value of the callback
        return "test service return string"

    def create_service(self):
        # $ rosservice call /hal_402_drives_mgr abcd
        # will call the function callback, that will receive the
        # service message as an argument
        # testin routine:
        # self.service = rospy.Service('hal_402_drives_mgr',
        #                             srv_robot_state,
        #                             self.cb_test_service)
        self.service = rospy.Service('hal_402_drives_mgr',
                                     srv_robot_state,
                                     self.cb_robot_state_service)
        rospy.loginfo("%s: service %s created" %
                      (self.compname,
                       self.service.resolved_name))

    def inspect_hal_pins(self):
        for key, drive in self.drives.items():
            drive.read_halpins()
            drive.calculate_status_word()
            drive.calculate_state()
            # print('{}: {} status_word: {:#010b} status: {}'.format(
            #                                        self.compname,
            #                                        drive.drive_name,
            #                                        drive.curr_status_word,
            #                                        drive.curr_state))

    def publish_states(self):
        for key, drive in self.drives.items():
            drive.publish_state()

    def run(self):
        while not rospy.is_shutdown():
            self.inspect_hal_pins()
            self.publish_states()
            self.rate.sleep()