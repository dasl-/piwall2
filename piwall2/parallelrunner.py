import shlex
import subprocess
from piwall2.logger import Logger

class ParallelRunner:

    __logger = None

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)

    # todo: possible to prefix output with machine name?
    def run_cmds(self, cmds):
        parallel_cmd = (
            "parallel --will-cite " +
            "--max-procs 0 " + # 0 means as many as possible
            # exit when the first job fails. Kill running jobs.
            # If fail=1 is used, the exit status will be the exit status of the failing job.
            "--halt now,fail=1 "
        )
        self.__logger.debug(f'parallel_cmd: {parallel_cmd}')
        proc = subprocess.Popen(
            parallel_cmd, shell = True, executable = '/usr/bin/bash', start_new_session = True,
            stdin = subprocess.PIPE
        )
        for cmd in cmds:
            proc.stdin.write(cmd)
            proc.stdin.flush()
        proc.stdin.close()
        return proc

    def quote_machines(self, machines, sep = ' '):
        ret = ''
        for machine in machines:
            ret += shlex.quote(machine) + sep
        return ret.strip(sep)
