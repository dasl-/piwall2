import shlex
import subprocess
from piwall2.directoryutils import DirectoryUtils
from piwall2.logger import Logger

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
            f"--machine '{machines}' " +
            f"-- {cmd}"
        )

        # subprocess.
        
    def quote_machines(self, machines, sep = ','):
        for machine in machines:
            machines += shlex.quote(machine) + ' '
        return machines.strip()
