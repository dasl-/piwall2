import shlex
import socket
import subprocess
import time

from piwall2.configloader import ConfigLoader
from piwall2.logger import Logger

class CmdRunner:

    # For passwordless ssh from the broadcaster to the receivers.
    # See: https://github.com/dasl-/piwall2/blob/main/utils/setup_broadcaster_and_receivers
    SSH_KEY_PATH = '/home/pi/.ssh/piwall2_broadcaster/id_ed25519'
    # Lack of space after `-i` is necessary: https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=578683#10
    SSH_KEY_PATH_FLAG = f'-i{SSH_KEY_PATH}'
    STANDARD_SSH_OPTS = [
        '-o UserKnownHostsFile=/dev/null',
        '-o StrictHostKeyChecking=no',
        '-o LogLevel=ERROR',
        '-o ConnectTimeout=5'
    ]
    __CONCURRENCY_LIMIT = 16

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        config_loader = ConfigLoader()
        self.__receivers_list = config_loader.get_receivers_list()

        # populate self.__broadcaster_and_receivers_list
        broadcaster_hostname = self.get_broadcaster_hostname()
        broadcaster_ip = socket.gethostbyname(broadcaster_hostname)
        self.__broadcaster_and_receivers_list = list(self.__receivers_list)
        if (
            broadcaster_hostname not in self.__broadcaster_and_receivers_list and
            broadcaster_ip not in self.__broadcaster_and_receivers_list
        ):
            self.__broadcaster_and_receivers_list.insert(0, broadcaster_hostname)

    def run_dsh(self, cmd, include_broadcaster = True):
        machines_list = self.__receivers_list
        if include_broadcaster:
            machines_list = self.__broadcaster_and_receivers_list

        machines_string = ''
        for machine in machines_list:
            machines_string += f'pi@{machine},'
        machines_string = machines_string.rstrip(',')
        ssh_opts = ''
        for ssh_opt in self.STANDARD_SSH_OPTS:
            ssh_opts += f"--remoteshellopt '{ssh_opt}' "
        dsh_cmd = (f"dsh -r ssh --forklimit {self.__CONCURRENCY_LIMIT} {ssh_opts}" +
            f'--remoteshellopt "{self.SSH_KEY_PATH_FLAG}" ' +
            f"--show-machine-names --machine {machines_string} {shlex.quote(cmd)}")
        self.run_cmd_with_realtime_output(dsh_cmd)

    def run_parallel(self, cmd, include_broadcaster = True):
        machines_list = self.__receivers_list
        if include_broadcaster:
            machines_list = self.__broadcaster_and_receivers_list
        machines_string = ' '.join(machines_list)

        parallel_cmd = (
            f"parallel --will-cite --max-procs {self.__CONCURRENCY_LIMIT} " +
            # exit when the first job fails. Kill running jobs.
            # If fail=1 is used, the exit status will be the exit status of the failing job.
            "--halt now,fail=1 " +
            f"{shlex.quote(cmd)} ::: {machines_string}"
        )
        self.run_cmd_with_realtime_output(parallel_cmd)

    def run_cmd_with_realtime_output(self, cmd, raise_on_failure = True):
        self.__logger.info(f"Running command: {cmd}")
        proc = subprocess.Popen(
            cmd, shell = True, executable = '/usr/bin/bash'
        )
        while proc.poll() is None:
            time.sleep(0.1)
        if proc.returncode != 0 and raise_on_failure:
            raise Exception(f"The process for cmd: [{cmd}] exited non-zero: " +
                f"{proc.returncode}.")
        return proc.returncode

    def get_broadcaster_and_receivers_hostname_list(self):
        return self.__broadcaster_and_receivers_list

    def get_receivers_hostname_list(self):
        return self.__receivers_list

    # this is intended to be run from the broadcaster
    def get_broadcaster_hostname(self):
        return socket.gethostname() + ".local"
