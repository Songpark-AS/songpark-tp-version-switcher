from __future__ import print_function, unicode_literals
import os, sys, tempfile, shutil
from PyInquirer import style_from_dict, Token, prompt, Separator
from pprint import pprint

VERSIONS_AVAILABLE_DIR = '/opt/songpark/versions_available'
VERSION_IN_USE_LINK = '/opt/songpark/version_in_use'
FPGA_FILENAMES = ['BOOT.bin', 'uImage', 'devicetree.dtb']
FPGA_FILES_DESTINATION = '/boot/'
CONNECT_EXECUTABLE_DESTINATION = '/usr/local/bin'
SYSTEMD_SERVICES = ['sp-bridgeprogram']

PROMPT_STYLE = style_from_dict({
    Token.Separator: '#cc5454',
    Token.QuestionMark: '#673ab7 bold',
    Token.Selected: '#cc5454',  # default
    Token.Pointer: '#673ab7 bold',
    Token.Instruction: '',  # default
    Token.Answer: '#f44336 bold',
    Token.Question: '',
})

def process_exited_normally(exit_code):
    return os.WIFEXITED(os.WEXITSTATUS(exit_code))

# a symlink method that is able to overwrite existing symlinks
def symlink(target, link_name, overwrite=False):
    '''
    Create a symbolic link named link_name pointing to target.
    If link_name exists then FileExistsError is raised, unless overwrite=True.
    When trying to overwrite a directory, IsADirectoryError is raised.
    '''

    if not overwrite:
        os.symlink(target, link_name)
        return

    # os.replace() may fail if files are on different filesystems
    link_dir = os.path.dirname(link_name)

    # Create link to target with temporary filename
    while True:
        temp_link_name = tempfile.mktemp(dir=link_dir)

        # os.* functions mimic as closely as possible system functions
        # The POSIX symlink() returns EEXIST if link_name already exists
        # https://pubs.opengroup.org/onlinepubs/9699919799/functions/symlink.html
        try:
            os.symlink(target, temp_link_name)
            break
        except FileExistsError:
            pass

    # Replace link_name with temp_link_name
    try:
        # Pre-empt os.replace on a directory with a nicer message
        if not os.path.islink(link_name) and os.path.isdir(link_name):
            raise IsADirectoryError(f"Cannot symlink over existing directory: '{link_name}'")
        os.replace(temp_link_name, link_name)
    except:
        if os.path.islink(temp_link_name):
            os.remove(temp_link_name)
        raise

def mount_boot_partition():
    # This method will attempt to mount the boot partition
    try:
        exit_code = os.system('mount /dev/mmcblk0p1 /boot')
        if not process_exited_normally(exit_code):
            raise Exception("Mount command exited with a non-zero exit-code!")
    except Exception as e:
        pprint(f'Failed to mount boot partition: {e}')
        sys.exit(1)


def run_systemd_command(servicename, command='stop'):
    # This method should modify a systemd service state to bring a service down/up
    exit_code = os.system(f'systemctl {command} {servicename}')
    if not process_exited_normally(exit_code):
        print(f"Failed to run {command} on systemd service {servicename}")
        sys.exit(1)

def switch_version(version):
    version_abspath = os.path.join(os.path.abspath(VERSIONS_AVAILABLE_DIR), version)
    version_in_use_abspath = os.path.abspath(VERSION_IN_USE_LINK)
    md5_hash_file = os.path.join(version_abspath, 'hash.md5')
    print(f'Changing to version: {version}')
    mount_boot_partition()


    # TODO: maybe use a manifest file to check if the neccessary files exists
    # if the structure of the version changes
    # this would also ensure backwards compatibility

    # Check if all neccessary files exists
    # FPGA files
    fpga_files = os.listdir(os.path.join(version_abspath, 'fpga'))
    fpga_files_dir = os.path.join(version_abspath, 'fpga')
    connect_files_dir = os.path.join(version_abspath, 'connect')
    fpga_files_exists = all(file in fpga_files for file in FPGA_FILENAMES)
    if not fpga_files_exists:
        print(f"FPGA files is missing in version: {version}")
        sys.exit(1)

    # Check if connect executable exists
    if not os.path.isfile(os.path.join(connect_files_dir, 'connect')):
        print(f"Connect executable is missing in version: {version}")
        sys.exit(1)

    # If signature file exist, test the files
    if os.path.isfile(md5_hash_file):
        print("checking MD5 hashes")
        prev_cwd = os.getcwd()
        os.chdir(version_abspath)
        exit_code = os.system(f'md5sum -c {md5_hash_file}')
        if not process_exited_normally(exit_code):
            print("MD5 mismatch!")
            sys.exit(1)
        else:
            os.chdir(prev_cwd)
            print("MD5 matched")
    else:
        questions = [{
            'type': 'confirm',
            'message': 'No MD5 hash file provided! continue anyway?',
            'name': 'continue',
            'default': False
        }]
        answers = prompt(questions, style=PROMPT_STYLE)
        if not answers['continue']:
            sys.exit(0)

    # stop running systemd services
    for service in SYSTEMD_SERVICES:
        run_systemd_command(service, command='stop')

    # copy connect program
    shutil.copyfile(os.path.join(connect_files_dir, 'connect'), os.path.join(CONNECT_EXECUTABLE_DESTINATION, 'connect'))

    # copy fpga files
    for file in fpga_files:
        shutil.copyfile(os.path.join(fpga_files_dir, file), os.path.join(FPGA_FILES_DESTINATION, file))

    # Everything went well
    # change the symlink
    symlink(version_abspath, version_in_use_abspath, overwrite=True)

    # prompt the user if we should reboot
    questions = [{
        'type': 'confirm',
        'message': 'Reboot the system?',
        'name': 'reboot',
        'default': True
    }]
    answers = prompt(questions, style=PROMPT_STYLE)
    if answers['reboot']:
        # reboot
        os.system('reboot')

def main():
    # Get the path to the current version in use
    version_in_use_path = False
    try:
        version_in_use_path = os.path.abspath(os.readlink(VERSION_IN_USE_LINK))
    except FileNotFoundError as e:
        print("No version currently in use found")


    choices = [Separator('=== Versions available ===')]

    versions_available_directories = os.listdir(VERSIONS_AVAILABLE_DIR)
    versions_available_directories.sort()
    for version in versions_available_directories:
        # Don't add the current version in use as a choice
        if os.path.join(os.path.abspath(VERSIONS_AVAILABLE_DIR), version) == version_in_use_path:
            continue
        choices.append(version)

    questions = [
        {
            'type': 'list',
            'message': 'Select version',
            'name': 'version',
            'choices': choices,
        }
    ]

    if len(choices) > 1:
        answer = prompt(questions, style=PROMPT_STYLE)
        switch_version(answer['version'])
    else:
        print("There are no versions available to choose")

if __name__ == "__main__":
    main()
