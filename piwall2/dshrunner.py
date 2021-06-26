import shlex
import subprocess
from piwall2.logger import Logger
from piwall2.broadcaster import Broadcaster

class DshRunner:

    __logger = None

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    def run_dsh(self, cmd, machines):
        machines = self.quote_machines(machines)
        dsh_cmd = (
            "dsh --concurrent-shell " + 
            "--remoteshellopt '-o ConnectTimeout=5' " +
            "--remoteshellopt '-o UserKnownHostsFile=/dev/null' " +
            "--remoteshellopt '-o StrictHostKeyChecking=no' " + 
            "--remoteshellopt '-o LogLevel=ERROR' " + 
            "--remoteshellopt '-o PasswordAuthentication=no' " +
            f"--remoteshellopt \"-o IdentityFile={shlex.quote(Broadcaster.SSH_KEY_PATH)}\" " +
            f"--machine '{machines}' " +
            f"-- {cmd}"
        )

        return subprocess.Popen(dsh_cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True)
        
    def quote_machines(self, machines, sep = ','):
        ret = ''
        for machine in machines:
            ret += shlex.quote(machine) + ' '
        return ret.strip()
