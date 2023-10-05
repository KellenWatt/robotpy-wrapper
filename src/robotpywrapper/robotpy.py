#!/usr/bin/env python3

import importlib.util
import subprocess
import sys
import os
import os.path

import configparser
import argparse
from typing import Any
import shlex


verbose_level = 1

def python(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    #  cmd = ["python3"]
    #  if sys.platform == "win32":
    #      cmd = ["py","-3"]
    global verbose_level
    if "capture_output" not in kwargs:
        kwargs["capture_output"] = verbose_level <= 1
    return subprocess.run([sys.executable] + args, text=True, **kwargs)

def rpinst(args: list[str]) -> subprocess.CompletedProcess:
    global verbose_level
    return python(["-m", "robotpy_installer"] + args)

def is_robotpy_addon(name: str) -> bool:
    return name in ["ctre", "navx", "photonvision", "pathplannerlib", "rev", "apriltag", "commands2", "commands-v2", "cscore", "romi", "sim"]

def format_robotpy_addon(name: str) -> str:
    if name == "commands2":
        name = "commands-v2"
    return "robotpy-"+name

def msg(m: str, target=sys.stdout) -> None:
    global verbose_level
    if (verbose_level < 1 and target != sys.stderr) or verbose_level < 0:
        return
    print("{}: {}".format(os.path.basename(sys.argv[0]), m), file=target)

def warn(m: str, *args: Any) -> None:
    m = m.format(*args)
    msg("warning: {}".format(m))

def error(m: str, *args: Any) -> None:
    m = m.format(*args)
    msg("error: {}".format(m), target=sys.stderr)

def fatal(m: str, *args: Any) -> None:
    m = m.format(*args)
    msg("fatal: {}".format(m), sys.stderr)
    sys.exit(1)

def expect_result(result: subprocess.CompletedProcess, msg: str, absolute: bool = True) -> None:
    if result.returncode != 0:
        if absolute:
            fatal(msg)
        else:
            error(msg)

def move_to_robotpy_dir() -> None:
    while not os.path.isfile(".robotpy"):
        os.chdir("..")
        if os.path.dirname(os.getcwd()) == os.getcwd():
            fatal("Current directory is not in a robotpy project")

config = None
def load_config() -> configparser.ConfigParser:
    global config
    if config is None:
        config = configparser.ConfigParser()
        config.read(".robotpy")
    return config

packages = None
def load_packages(refresh: bool = False) -> dict[str, str]:
    global packages
    if packages is None or refresh:
        res = python(["-m", "pip", "freeze"], capture_output=True)
        if res.returncode != 0:
            fatal("Couldn't load installed packages.")
        reqs = res.stdout.splitlines()
        splits = [desc.split("==") for desc in reqs]
        # just ignore local packages for now
        reqs = {req[0]: req[1] for req in splits if len(req) == 2}
        packages = reqs
    return packages
    

def install_package(pkgs: list[str], download: bool = True) -> None:
    if len(pkgs) == 0:
        return

    config = load_config()

    for pkg in pkgs:
        msg("Installing package '{}'".format(pkg))
        res = python(["-m", "pip", "install", "--upgrade", pkg])
        expect_result(res, "Installing package failed unexpectedly", absolute=False)
        if res.returncode != 0:
            continue

        if download:
            msg("Downloading package '{}' for robot installations".format(pkg))
            res = rpinst(["download", pkg])
            expect_result(res, "Downloading package for remote use failed unexpectedly", absolute=False)
            if res.returncode != 0:
                continue

            packages = load_packages(refresh=True)

            if pkg not in config["requirements"] or config["requirements"][pkg] < packages[pkg]:
                config["requirements"][pkg] = packages[pkg]


    

def initialize(args) -> None:

    target = args.directory
    if target is not None:
        if os.path.exists(args.directory) and not os.path.isdir(args.directory):
            fatal("{} already exists but is not a directory".format("args.directory"))
        os.makedirs(args.directory, exist_ok=True)
    else:
        target = os.path.abspath(".")

    os.chdir(target)
    # Only do initialization work after this point

    config = load_config()
    if os.path.isfile(".robotpy"):
        msg("{} already exists. If you want to reset, delete the file an re-run `robotpy init`".format(os.path.join(target, ".robotpy")))
    else:
        config["requirements"] = {"robotpy": packages["robotpy"]}
        #  with open(".robotpy", "w") as f:
        #      packages = load_packages()
        #      f.write("[requirements]\nrobotpy = {}".format(packages["robotpy"]))

    config["execution"] = {"main": args.main}
    
    if args.host is not None:
        auth = "[auth]\nhostname = {}\n".format(args.host)
        with open(".deploy_cfg", "w") as f:
            f.write(auth)
        with open(".installer_cfg", "w") as f:
            f.write(auth)
        config["auth"] = {"hostname": args.host}

    if not args.bare:
        if os.path.isfile(args.main):
            error("{} already exists. Skipping main file creation.", args.main)
        else:
            with open(args.main, "w") as f:
                f.write(
"""import wpilib

class Robot(wpilib.TimedRobot):
    def robotInit(self) -> None:
        pass

    def robotPeriodic(self) -> None:
        pass

    def autonomousInit(self) -> None:
        pass

    def autonomousPeriodic(self) -> None:
        pass

    def teleopInit(self) -> None:
        pass

    def teleopPeriodic(self) -> None:
        pass


if __name__ == "__main__":
    wpilib.run(Robot)
""")

    if args.git:
        subprocess.run(["git", "init"])

    msg("Downloading python for robot installation")
    res = rpinst(["download-python"])
    expect_result(res, "Downloading Python failed unexpectedly")

    msg("Downloading robotpy for robot installations")
    res = rpinst(["download", "robotpy"])
    expect_result(res, "Downloading robotpy for remote use failed unexpectedly")
 
    pkgs = [(format_robotpy_addon(name) if is_robotpy_addon(name) else name) for name in args.packages]
    install_package(pkgs)
   

def remove(args) -> None:
    move_to_robotpy_dir()
    config = load_config()
    for pkg in args.packages:
        if pkg == "robotpy":
            error("robotpy can't be removed from requirements")
            continue
        
        if pkg in config["requirements"]:
            del config["requirements"][pkg]
        else:
            error("'{}' is not installed in this project", pkg)

def install(args) -> None:
    #download for robot and install local simultaneously
    # inspect packages. If contains shorthand for component, install expanded package name (support 'all')
    # store robotpy installed packages to (global?) file, including if downloaded for remote.
    move_to_robotpy_dir()

    pkgs = [(format_robotpy_addon(name) if is_robotpy_addon(name) else name) for name in args.packages]
        
    install_package(pkgs, download = args.download)


def update(args) -> None:
    move_to_robotpy_dir()
    config = load_config()
    pkgs = args.packages
    if len(pkgs) == 0:
        pkgs = [pkg for pkg in config["requirements"]]
        pkgs = ["robotpy"] + pkgs

    for pkg in pkgs:
        if pkg not in config["requirements"]:
            warn("'{}' is not a registered package. Use `robotpy install {}` instead", pkg, pkg)

    pkgs = [pkg for pkg in pkgs if pkg in config["requirements"]]

    install_package(pkgs, download=args.download)


def deploy(args) -> None:
    # deployed packages have their pair stored in a "requirements.deployed" section in the config.
    # Any requirements that have a higher version number than the deployed get deployed. (or all  if the section doesn't exist)
    move_to_robotpy_dir()
    config = load_config()
    if args.deploy_lib:
        deployed = config["requirements.deployed"]
        pkgs = config["requirements"]

        updates = [pkg for pkg in pkgs if pkg not in deployed or deployed[pkg] < pkgs[pkg]]

        if len(updates) != 0:
            msg("Package requirements updated since last deploy")
            msg("Updating packages on remote target")
            res = rpinst(["install"] + updates)
            expect_result(res, "Updating packages on remote target failed unexpectedly")

            config["requirements.deployed"] = config["requirements"]

    if args.deploy_code:
        msg("Deploying robot code (main: {})".format(config["execution"]["main"]))
        res = python([config["execution"]["main"], "deploy"])
        expect_result(res, "Deploying robot code failed unexpectedly")


def configure(args) -> None:
    move_to_robotpy_dir()
    config = load_config()
    field = args.field
    if "." not in field:
        error("{} is not a valid config field", field)
        sys.exit(1)
    parts = field.split(".")
    group = ".".join(parts[:-1])
    name = parts[-1]

    if group in ["requirements", "requirements.deployed"]:
        error("Cannot change requirements using `config`. Use `robotpy install` instead.")
        sys.exit(1)

    if args.clear:
        if group in config and name in config[group]:
            del config[group][name]
            if len(config[group]) == 0:
                del config[group]
    elif args.value is not None:
        if group not in config:
            config[group] = {}
        config[group][name] = args.value
    else:
        if group in config and name in config[group]:
            print(config[group][name])


parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers(required=True)

parser.set_defaults(verbose_level=1)
parser.add_argument("-v", "--verbose", action="store_const", dest="verbose_level", const=2)
parser.add_argument("-q", "--quiet", action="store_const", dest="verbose_level", const=0)
parser.add_argument("--silent", action="store_const", dest="verbose_level", const=-1)

init_parser = subparsers.add_parser("initialize", aliases=["init"])
init_parser.add_argument("-m", "--main", default="robot.py")
init_parser.add_argument("--bare", action="store_true")
init_parser.add_argument("--host", dest="host")
init_parser.add_argument("-t", "--team", dest="host")
init_parser.add_argument("--git", action=argparse.BooleanOptionalAction, default=True)
# requires 3.8+
init_parser.add_argument("--with", dest="packages", nargs="+", action="extend", default=[])
init_parser.add_argument("directory", nargs="?")
init_parser.set_defaults(func=initialize)

# install [--[no-]download] {packages}
install_parser = subparsers.add_parser("install")
install_parser.set_defaults(func=install)
install_parser.add_argument("--download", action=argparse.BooleanOptionalAction, default=True)
install_parser.add_argument("packages", nargs="+")

# handles updates to robotpy (can accept components)
update_parser = subparsers.add_parser("update")
update_parser.set_defaults(func=update)
update_parser.add_argument("--download", action=argparse.BooleanOptionalAction, default=True)
update_parser.add_argument("packages", nargs="*")

remove_parser = subparsers.add_parser("remove")
remove_parser.set_defaults(func=remove)
remove_parser.add_argument("packages", nargs="+")


deploy_parser = subparsers.add_parser("deploy")
deploy_parser.set_defaults(func=deploy)
deploy_parser.add_argument("--no-code", dest="deploy_code", action="store_false")
deploy_parser.add_argument("--no-lib", dest="deploy_lib", action="store_false")
#  deploy_parser.add_argument("--analyze", action=argparse.BooleanOptionalAction, default=True)


config_parser = subparsers.add_parser("config")
config_parser.set_defaults(func=configure)
config_parser.add_argument("field")
config_parser.add_argument("value", nargs="?")
config_parser.add_argument("--clear", action="store_true")


def main() -> None:
    global verbose_level
    global subparsers

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)
    
    config = load_config()
    if "command" in config:
        commands = config["command"]
        for command in commands:
            custom = subparsers.add_parser(command)
            custom.add_argument("rest", nargs=argparse.REMAINDER)
            custom.set_defaults(func=lambda args: subprocess.run(shlex.split(commands[command]) + args.rest))


    args = parser.parse_args()
    verbose_level = args.verbose_level
    args.func(args)

    with open(".robotpy", "w") as f:
        config.write(f)


if __name__ == "__main__":
    main()