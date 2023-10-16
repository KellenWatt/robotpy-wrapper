#!/usr/bin/env python3

import subprocess
import sys
import os
import os.path

import configparser
import argparse
from typing import Any
import shlex


verbose_level = 1
skeleton_main = """import wpilib

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
"""

def has_git_installed():
    res = subprocess.run(["git", "--version"])
    return res.returncode == 0


def python(args: list[str], **kwargs) -> subprocess.CompletedProcess:
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

def expect_result(result: subprocess.CompletedProcess, msg: str, absolute: bool = True) -> bool:
    if result.returncode != 0:
        if absolute:
            fatal(msg)
        else:
            error(msg)
    return result.returncode == 0

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

def write_auth_config() -> None:
    config = load_config()

    auth = "[auth]\nhostname = {}\n".format(config["auth"]["hostname"])
    with open(".deploy_cfg", "w") as f:
        f.write(auth)
    with open(".installer_config", "w") as f:
        f.write(auth)

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
        packages = load_packages()
        config["requirements"] = {"robotpy": packages["robotpy"]}

    config["exec"] = {"main": args.main}
    
    if args.host is not None:
        config["auth"] = {"hostname": args.host}
        write_auth_config()

    if not args.bare:
        if os.path.isfile(args.main):
            error("{} already exists. Skipping main file creation.", args.main)
        else:
            with open(args.main, "w") as f:
                f.write(skeleton_main)

    if args.git:
        if has_git_installed():
            subprocess.run(["git", "init"])
        else:
            warn("can't find git. Skipping git initialization")

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
        if is_robotpy_addon(pkg):
            pkg = format_robotpy_addon(pkg)
        
        if pkg in config["requirements"]:
            del config["requirements"][pkg]
        else:
            error("'{}' is not installed in this project", pkg)

def install(args) -> None:
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

def run_checks(tools) -> None:
    move_to_robotpy_dir() # not strictly necessary, but can't hurt
    config = load_config()

    stop_on_fail = True
    if "analyze" in config and "onfail" in config["analyze"]:
        if config["analyze"]["onfail"] == "continue":
            stop_on_fail = False

    for tool in tools:
        msg("running analyzer: {}".format(tool))
        res = subprocess.run([tool, config["exec"]["main"]])
        expect_result(res, "{} failed".format(tool), absolute=stop_on_fail)


def analyze(args) -> None:
    move_to_robotpy_dir()
    config = load_config()
    if args.add is not None:
        packages = load_packages()
        tools = []
        for tool in args.add:
            if "analyze.tools" in config and tool in config["analyze.tools"]:
                msg("{} is already registered".format(tool))
                continue
            if tool not in packages:
                msg("{} not found. Attempting to install using pip.".format(tool))
                res = python(["-m", "pip", "install", tool])
                if expect_result(res, "Installation failed. Skipping {}".format(tool), absolute=False):
                    msg("analyzer '{}' added".format(tool))
                    tools.append(tool)
            else:
                msg("analyzer '{}' added".format(tool))
                tools.append(tool)

        packages = load_packages(refresh=True)

        if "analyze.tools" not in config and len(tools) != 0:
            config["analyze.tools"] = {}

        for tool in tools:
            config["analyze.tools"][tool] = packages[tool]
    elif args.remove is not None:
        if "analyze.tools" not in config:
            msg("no tools registered")
            sys.exit(1)
        for tool in args.remove:
            if tool in config["analyze.tools"]:
                del config["analyze.tools"][tool]
                msg("analyzer '{}' removed".format(tool))
            else:
                warn("{} is not a rgistered analyzer", tool)
        if len(config["analyze.tools"]) == 0:
            del(config["analyze.tools"])
    elif args.list:
        if "analyze.tools" not in config:
            return
        for tool in config["analyze.tools"]:
            print(tool)
    else:
        if "analyze.tools" not in config:
            warn("no analyzers registered in this project")
            return

        tools = [tool for tool in config["analyze.tools"]]
        if args.use is not None:
            for tool in args.use:
                if tool not in tools:
                    warn("'{}' is not a registered analyzer for this project", tool)
                    continue
            tools = [tool for tool in tools if tool in args.use]
        run_checks(tools) 



def deploy(args) -> None:
    # deployed packages have their pair stored in a "requirements.deployed" section in the config.
    # Any requirements that have a higher version number than the deployed get deployed. (or all  if the section doesn't exist)
    move_to_robotpy_dir()
    config = load_config()

    if not "auth" in config or not "hostname" in config["auth"]:
        host = input("Enter host name or team number: ").strip()
        if len(host) == 0:
            fatal("No hostname supplied")
        
        if "auth" not in config:
            config["auth"] = {}
        config["auth"]["hostname"] = host
        write_auth_config()

    if args.deploy_lib:
        if "requirements.deployed" not in config:
            config["requirements.deployed"] = {}
        
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
        if args.analyze and "analyze.tools" in config:
            msg("running analyzer checks before deploy")
            tools = config["analyze.tools"]

            run_checks(tools)
            

        msg("Deploying robot code (main: {})".format(config["exec"]["main"]))
        res = python([config["exec"]["main"], "deploy"])
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
        if group == "auth" and name == "hostname":
            write_auth_config()

    else:
        if group in config and name in config[group]:
            print(config[group][name])


parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers(required=True, title="subcommands", 
                                   description="These are the options you can use with the robotpy command", 
                                   metavar="<subcommand>")

parser.set_defaults(verbose_level=1)
parser.add_argument("-v", "--verbose", action="store_const", dest="verbose_level", const=2, 
                    help="set output to show the output of underlying commands (pip, robotpy_installer, etc.)")
parser.add_argument("-q", "--quiet", action="store_const", dest="verbose_level", const=0, 
                    help="don't show normal output. Still shows errors")
parser.add_argument("--silent", action="store_const", dest="verbose_level", const=-1, 
                    help="don't show any output, even errors")

init_parser = subparsers.add_parser("initialize", aliases=["init"], 
                                    help="Creates a new RobotPy project", usage="%(prog)s [<options>] [directory]")
init_parser.add_argument("-m", "--main", default="robot.py", help="set main file to MAIN")
init_parser.add_argument("--bare", action="store_true", help="don't create any skeleton files")
init_parser.add_argument("--host", dest="host", help="set the hostname of the eventual target")
init_parser.add_argument("-t", "--team", dest="host", help="alias for --host")
init_parser.add_argument("--git", action=argparse.BooleanOptionalAction, default=True, help="create git repo in new project (default: true)")
# requires 3.8+
init_parser.add_argument("--with", dest="packages", nargs="+", action="extend", default=[], help="install packages alongside initialization")
init_parser.add_argument("directory", nargs="?", help="create project inside directory (default: current directory)")
init_parser.set_defaults(func=initialize)

# install [--[no-]download] {packages}
install_parser = subparsers.add_parser("install", help="Installs packages to current project", 
                                       usage="%(prog)s [<options>] <packages>", 
                                       epilog="Specifying --no-download makes this command work almost like `pip install <packages>`")
install_parser.set_defaults(func=install)
install_parser.add_argument("--download", action=argparse.BooleanOptionalAction, 
                            help="download the package for use on the robot (default: true)")
install_parser.add_argument("packages", nargs="+", help="packages to install")

# handles updates to robotpy (can accept components)
update_parser = subparsers.add_parser("update", help="Updates installed packages (including robotpy)", usage="%(prog)s [<options>] [<packages>]")
update_parser.set_defaults(func=update)
update_parser.add_argument("--download", action=argparse.BooleanOptionalAction, 
                           help="download the updated package for use on the robot (default: true)")
update_parser.add_argument("packages", nargs="*", help="packages to update. All if not specified")

remove_parser = subparsers.add_parser("remove", help="Unregisters packages from current project", usage="%(prog)s <packages>")
remove_parser.set_defaults(func=remove)
remove_parser.add_argument("packages", nargs="+", help="packages to remove")


check_parser = subparsers.add_parser("analyze", help="Manages and executes static analyzers", 
                                     usage="%(prog)s [-h] [-l | -a <tools>] | -r <tools> | --use <tools>]")
check_parser.set_defaults(func=analyze)
check_group = check_parser.add_mutually_exclusive_group()
check_group.add_argument("-a", "--add", nargs="+", help="add tool(s) to project")
check_group.add_argument("-l", "--list", action="store_true", help="print registered tools")
check_group.add_argument("--use", nargs="+", help="use only selected tool(s)")
check_group.add_argument("-r", "--remove", nargs="+", help="remove tool(s) from project")

deploy_parser = subparsers.add_parser("deploy", help="Deploys code and libraries to the robot", usage="%(prog)s [<options>]")
deploy_parser.set_defaults(func=deploy)
deploy_parser.add_argument("--no-code", dest="deploy_code", action="store_false", help="prevent code from being deployed")
deploy_parser.add_argument("--no-lib", dest="deploy_lib", action="store_false", help="prevent libraries from being updated")
deploy_parser.add_argument("--analyze", action=argparse.BooleanOptionalAction, help="statically analyze code before deploy (default: true)")


config_parser = subparsers.add_parser("config", help="Get and set project options", 
                                      usage="%(prog)s [<options>] key [value]", 
                                      formatter_class=argparse.RawDescriptionHelpFormatter,
                                      epilog="Keys are specified in the <group>.<field> format (all but the last '.' are part\n"\
                                              "of the group name). Any name without a period is invalid. Changing anything in\n"\
                                              "the 'requirements' or 'requirements.deployed' groups is disallowed.")
config_parser.set_defaults(func=configure)
config_parser.add_argument("field", help="dot-separated name of the setting")
config_parser.add_argument("value", nargs="?", help="value to be set. Displays the current value if not given")
config_parser.add_argument("--clear", action="store_true", help="unset the field")


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
