import os

s=os.popen('ps -ef | grep bot.py').read().split('\n')[0].split()[1]
os.system(f"kill -9 {s}")