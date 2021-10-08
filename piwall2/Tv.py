"""
Represents a TV. A receiver may have one or two TVs (one if using component output,
and up to two if using HDMI output).

A "tv_id" uniquely identifies a TV. Its format is: <receiver_hostname>_<tv_num>
where tv_num is either "1" or "2". For example: "piwall2.local_1"
"""
class Tv:
    
    __DELIM = '_'

    def __init__(self, receiver_hostname, tv_number):
        self.hostname = receiver_hostname
        self.tv_number = tv_number
        self.tv_id = f'{self.hostname}{self.__DELIM}{self.tv_number}'

    @staticmethod
    def get_hostname_from_tv_id(tv_id):
        return tv_id.split(Tv.__DELIM)[0]

    @staticmethod
    def get_tv_num_from_tv_id(tv_id):
        return int(tv_id.split(Tv.__DELIM)[1])
