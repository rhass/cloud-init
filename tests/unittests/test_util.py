# This file is part of cloud-init. See LICENSE file for license information.

from __future__ import print_function

import logging
import os
import shutil
import stat
import tempfile

import six
import yaml

from cloudinit import importer, util
from . import helpers

try:
    from unittest import mock
except ImportError:
    import mock


class FakeSelinux(object):

    def __init__(self, match_what):
        self.match_what = match_what
        self.restored = []

    def matchpathcon(self, path, mode):
        if path == self.match_what:
            return
        else:
            raise OSError("No match!")

    def is_selinux_enabled(self):
        return True

    def restorecon(self, path, recursive):
        self.restored.append(path)


class TestGetCfgOptionListOrStr(helpers.TestCase):
    def test_not_found_no_default(self):
        """None is returned if key is not found and no default given."""
        config = {}
        result = util.get_cfg_option_list(config, "key")
        self.assertIsNone(result)

    def test_not_found_with_default(self):
        """Default is returned if key is not found."""
        config = {}
        result = util.get_cfg_option_list(config, "key", default=["DEFAULT"])
        self.assertEqual(["DEFAULT"], result)

    def test_found_with_default(self):
        """Default is not returned if key is found."""
        config = {"key": ["value1"]}
        result = util.get_cfg_option_list(config, "key", default=["DEFAULT"])
        self.assertEqual(["value1"], result)

    def test_found_convert_to_list(self):
        """Single string is converted to one element list."""
        config = {"key": "value1"}
        result = util.get_cfg_option_list(config, "key")
        self.assertEqual(["value1"], result)

    def test_value_is_none(self):
        """If value is None empty list is returned."""
        config = {"key": None}
        result = util.get_cfg_option_list(config, "key")
        self.assertEqual([], result)


class TestWriteFile(helpers.TestCase):
    def setUp(self):
        super(TestWriteFile, self).setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_basic_usage(self):
        """Verify basic usage with default args."""
        path = os.path.join(self.tmp, "NewFile.txt")
        contents = "Hey there"

        util.write_file(path, contents)

        self.assertTrue(os.path.exists(path))
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            create_contents = f.read()
            self.assertEqual(contents, create_contents)
        file_stat = os.stat(path)
        self.assertEqual(0o644, stat.S_IMODE(file_stat.st_mode))

    def test_dir_is_created_if_required(self):
        """Verifiy that directories are created is required."""
        dirname = os.path.join(self.tmp, "subdir")
        path = os.path.join(dirname, "NewFile.txt")
        contents = "Hey there"

        util.write_file(path, contents)

        self.assertTrue(os.path.isdir(dirname))
        self.assertTrue(os.path.isfile(path))

    def test_explicit_mode(self):
        """Verify explicit file mode works properly."""
        path = os.path.join(self.tmp, "NewFile.txt")
        contents = "Hey there"

        util.write_file(path, contents, mode=0o666)

        self.assertTrue(os.path.exists(path))
        self.assertTrue(os.path.isfile(path))
        file_stat = os.stat(path)
        self.assertEqual(0o666, stat.S_IMODE(file_stat.st_mode))

    def test_copy_mode_no_existing(self):
        """Verify that file is created with mode 0o644 if copy_mode
        is true and there is no prior existing file."""
        path = os.path.join(self.tmp, "NewFile.txt")
        contents = "Hey there"

        util.write_file(path, contents, copy_mode=True)

        self.assertTrue(os.path.exists(path))
        self.assertTrue(os.path.isfile(path))
        file_stat = os.stat(path)
        self.assertEqual(0o644, stat.S_IMODE(file_stat.st_mode))

    def test_copy_mode_with_existing(self):
        """Verify that file is created using mode of existing file
        if copy_mode is true."""
        path = os.path.join(self.tmp, "NewFile.txt")
        contents = "Hey there"

        open(path, 'w').close()
        os.chmod(path, 0o666)

        util.write_file(path, contents, copy_mode=True)

        self.assertTrue(os.path.exists(path))
        self.assertTrue(os.path.isfile(path))
        file_stat = os.stat(path)
        self.assertEqual(0o666, stat.S_IMODE(file_stat.st_mode))

    def test_custom_omode(self):
        """Verify custom omode works properly."""
        path = os.path.join(self.tmp, "NewFile.txt")
        contents = "Hey there"

        # Create file first with basic content
        with open(path, "wb") as f:
            f.write(b"LINE1\n")
        util.write_file(path, contents, omode="a")

        self.assertTrue(os.path.exists(path))
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            create_contents = f.read()
            self.assertEqual("LINE1\nHey there", create_contents)

    def test_restorecon_if_possible_is_called(self):
        """Make sure the selinux guard is called correctly."""
        my_file = os.path.join(self.tmp, "my_file")
        with open(my_file, "w") as fp:
            fp.write("My Content")

        fake_se = FakeSelinux(my_file)

        with mock.patch.object(importer, 'import_module',
                               return_value=fake_se) as mockobj:
            with util.SeLinuxGuard(my_file) as is_on:
                self.assertTrue(is_on)

        self.assertEqual(1, len(fake_se.restored))
        self.assertEqual(my_file, fake_se.restored[0])

        mockobj.assert_called_once_with('selinux')


class TestDeleteDirContents(helpers.TestCase):
    def setUp(self):
        super(TestDeleteDirContents, self).setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def assertDirEmpty(self, dirname):
        self.assertEqual([], os.listdir(dirname))

    def test_does_not_delete_dir(self):
        """Ensure directory itself is not deleted."""
        util.delete_dir_contents(self.tmp)

        self.assertTrue(os.path.isdir(self.tmp))
        self.assertDirEmpty(self.tmp)

    def test_deletes_files(self):
        """Single file should be deleted."""
        with open(os.path.join(self.tmp, "new_file.txt"), "wb") as f:
            f.write(b"DELETE ME")

        util.delete_dir_contents(self.tmp)

        self.assertDirEmpty(self.tmp)

    def test_deletes_empty_dirs(self):
        """Empty directories should be deleted."""
        os.mkdir(os.path.join(self.tmp, "new_dir"))

        util.delete_dir_contents(self.tmp)

        self.assertDirEmpty(self.tmp)

    def test_deletes_nested_dirs(self):
        """Nested directories should be deleted."""
        os.mkdir(os.path.join(self.tmp, "new_dir"))
        os.mkdir(os.path.join(self.tmp, "new_dir", "new_subdir"))

        util.delete_dir_contents(self.tmp)

        self.assertDirEmpty(self.tmp)

    def test_deletes_non_empty_dirs(self):
        """Non-empty directories should be deleted."""
        os.mkdir(os.path.join(self.tmp, "new_dir"))
        f_name = os.path.join(self.tmp, "new_dir", "new_file.txt")
        with open(f_name, "wb") as f:
            f.write(b"DELETE ME")

        util.delete_dir_contents(self.tmp)

        self.assertDirEmpty(self.tmp)

    def test_deletes_symlinks(self):
        """Symlinks should be deleted."""
        file_name = os.path.join(self.tmp, "new_file.txt")
        link_name = os.path.join(self.tmp, "new_file_link.txt")
        with open(file_name, "wb") as f:
            f.write(b"DELETE ME")
        os.symlink(file_name, link_name)

        util.delete_dir_contents(self.tmp)

        self.assertDirEmpty(self.tmp)


class TestKeyValStrings(helpers.TestCase):
    def test_keyval_str_to_dict(self):
        expected = {'1': 'one', '2': 'one+one', 'ro': True}
        cmdline = "1=one ro 2=one+one"
        self.assertEqual(expected, util.keyval_str_to_dict(cmdline))


class TestGetCmdline(helpers.TestCase):
    def test_cmdline_reads_debug_env(self):
        with mock.patch.dict("os.environ",
                             values={'DEBUG_PROC_CMDLINE': 'abcd 123'}):
            ret = util.get_cmdline()
        self.assertEqual("abcd 123", ret)


class TestLoadYaml(helpers.TestCase):
    mydefault = "7b03a8ebace993d806255121073fed52"

    def test_simple(self):
        mydata = {'1': "one", '2': "two"}
        self.assertEqual(util.load_yaml(yaml.dump(mydata)), mydata)

    def test_nonallowed_returns_default(self):
        # for now, anything not in the allowed list just returns the default.
        myyaml = yaml.dump({'1': "one"})
        self.assertEqual(util.load_yaml(blob=myyaml,
                                        default=self.mydefault,
                                        allowed=(str,)),
                         self.mydefault)

    def test_bogus_returns_default(self):
        badyaml = "1\n 2:"
        self.assertEqual(util.load_yaml(blob=badyaml,
                                        default=self.mydefault),
                         self.mydefault)

    def test_unsafe_types(self):
        # should not load complex types
        unsafe_yaml = yaml.dump((1, 2, 3,))
        self.assertEqual(util.load_yaml(blob=unsafe_yaml,
                                        default=self.mydefault),
                         self.mydefault)

    def test_python_unicode(self):
        # complex type of python/unicode is explicitly allowed
        myobj = {'1': six.text_type("FOOBAR")}
        safe_yaml = yaml.dump(myobj)
        self.assertEqual(util.load_yaml(blob=safe_yaml,
                                        default=self.mydefault),
                         myobj)


class TestMountinfoParsing(helpers.ResourceUsingTestCase):
    def test_invalid_mountinfo(self):
        line = ("20 1 252:1 / / rw,relatime - ext4 /dev/mapper/vg0-root"
                "rw,errors=remount-ro,data=ordered")
        elements = line.split()
        for i in range(len(elements) + 1):
            lines = [' '.join(elements[0:i])]
            if i < 10:
                expected = None
            else:
                expected = ('/dev/mapper/vg0-root', 'ext4', '/')
            self.assertEqual(expected, util.parse_mount_info('/', lines))

    def test_precise_ext4_root(self):

        lines = self.readResource('mountinfo_precise_ext4.txt').splitlines()

        expected = ('/dev/mapper/vg0-root', 'ext4', '/')
        self.assertEqual(expected, util.parse_mount_info('/', lines))
        self.assertEqual(expected, util.parse_mount_info('/usr', lines))
        self.assertEqual(expected, util.parse_mount_info('/usr/bin', lines))

        expected = ('/dev/md0', 'ext4', '/boot')
        self.assertEqual(expected, util.parse_mount_info('/boot', lines))
        self.assertEqual(expected, util.parse_mount_info('/boot/grub', lines))

        expected = ('/dev/mapper/vg0-root', 'ext4', '/')
        self.assertEqual(expected, util.parse_mount_info('/home', lines))
        self.assertEqual(expected, util.parse_mount_info('/home/me', lines))

        expected = ('tmpfs', 'tmpfs', '/run')
        self.assertEqual(expected, util.parse_mount_info('/run', lines))

        expected = ('none', 'tmpfs', '/run/lock')
        self.assertEqual(expected, util.parse_mount_info('/run/lock', lines))

    def test_raring_btrfs_root(self):
        lines = self.readResource('mountinfo_raring_btrfs.txt').splitlines()

        expected = ('/dev/vda1', 'btrfs', '/')
        self.assertEqual(expected, util.parse_mount_info('/', lines))
        self.assertEqual(expected, util.parse_mount_info('/usr', lines))
        self.assertEqual(expected, util.parse_mount_info('/usr/bin', lines))
        self.assertEqual(expected, util.parse_mount_info('/boot', lines))
        self.assertEqual(expected, util.parse_mount_info('/boot/grub', lines))

        expected = ('/dev/vda1', 'btrfs', '/home')
        self.assertEqual(expected, util.parse_mount_info('/home', lines))
        self.assertEqual(expected, util.parse_mount_info('/home/me', lines))

        expected = ('tmpfs', 'tmpfs', '/run')
        self.assertEqual(expected, util.parse_mount_info('/run', lines))

        expected = ('none', 'tmpfs', '/run/lock')
        self.assertEqual(expected, util.parse_mount_info('/run/lock', lines))


class TestReadDMIData(helpers.FilesystemMockingTestCase):

    def setUp(self):
        super(TestReadDMIData, self).setUp()
        self.new_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.new_root)
        self.patchOS(self.new_root)
        self.patchUtils(self.new_root)

    def _create_sysfs_parent_directory(self):
        util.ensure_dir(os.path.join('sys', 'class', 'dmi', 'id'))

    def _create_sysfs_file(self, key, content):
        """Mocks the sys path found on Linux systems."""
        self._create_sysfs_parent_directory()
        dmi_key = "/sys/class/dmi/id/{0}".format(key)
        util.write_file(dmi_key, content)

    def _configure_dmidecode_return(self, key, content, error=None):
        """
        In order to test a missing sys path and call outs to dmidecode, this
        function fakes the results of dmidecode to test the results.
        """
        def _dmidecode_subp(cmd):
            if cmd[-1] != key:
                raise util.ProcessExecutionError()
            return (content, error)

        self.patched_funcs.enter_context(
            mock.patch.object(util, 'which', lambda _: True))
        self.patched_funcs.enter_context(
            mock.patch.object(util, 'subp', _dmidecode_subp))

    def patch_mapping(self, new_mapping):
        self.patched_funcs.enter_context(
            mock.patch('cloudinit.util.DMIDECODE_TO_DMI_SYS_MAPPING',
                       new_mapping))

    def test_sysfs_used_with_key_in_mapping_and_file_on_disk(self):
        self.patch_mapping({'mapped-key': 'mapped-value'})
        expected_dmi_value = 'sys-used-correctly'
        self._create_sysfs_file('mapped-value', expected_dmi_value)
        self._configure_dmidecode_return('mapped-key', 'wrong-wrong-wrong')
        self.assertEqual(expected_dmi_value, util.read_dmi_data('mapped-key'))

    def test_dmidecode_used_if_no_sysfs_file_on_disk(self):
        self.patch_mapping({})
        self._create_sysfs_parent_directory()
        expected_dmi_value = 'dmidecode-used'
        self._configure_dmidecode_return('use-dmidecode', expected_dmi_value)
        with mock.patch("cloudinit.util.os.uname") as m_uname:
            m_uname.return_value = ('x-sysname', 'x-nodename',
                                    'x-release', 'x-version', 'x86_64')
            self.assertEqual(expected_dmi_value,
                             util.read_dmi_data('use-dmidecode'))

    def test_dmidecode_not_used_on_arm(self):
        self.patch_mapping({})
        self._create_sysfs_parent_directory()
        dmi_val = 'from-dmidecode'
        dmi_name = 'use-dmidecode'
        self._configure_dmidecode_return(dmi_name, dmi_val)

        expected = {'armel': None, 'aarch64': dmi_val, 'x86_64': dmi_val}
        found = {}
        # we do not run the 'dmi-decode' binary on some arches
        # verify that anything requested that is not in the sysfs dir
        # will return None on those arches.
        with mock.patch("cloudinit.util.os.uname") as m_uname:
            for arch in expected:
                m_uname.return_value = ('x-sysname', 'x-nodename',
                                        'x-release', 'x-version', arch)
                found[arch] = util.read_dmi_data(dmi_name)
        self.assertEqual(expected, found)

    def test_none_returned_if_neither_source_has_data(self):
        self.patch_mapping({})
        self._configure_dmidecode_return('key', 'value')
        self.assertIsNone(util.read_dmi_data('expect-fail'))

    def test_none_returned_if_dmidecode_not_in_path(self):
        self.patched_funcs.enter_context(
            mock.patch.object(util, 'which', lambda _: False))
        self.patch_mapping({})
        self.assertIsNone(util.read_dmi_data('expect-fail'))

    def test_dots_returned_instead_of_foxfox(self):
        # uninitialized dmi values show as \xff, return those as .
        my_len = 32
        dmi_value = b'\xff' * my_len + b'\n'
        expected = ""
        dmi_key = 'system-product-name'
        sysfs_key = 'product_name'
        self._create_sysfs_file(sysfs_key, dmi_value)
        self.assertEqual(expected, util.read_dmi_data(dmi_key))


class TestMultiLog(helpers.FilesystemMockingTestCase):

    def _createConsole(self, root):
        os.mkdir(os.path.join(root, 'dev'))
        open(os.path.join(root, 'dev', 'console'), 'a').close()

    def setUp(self):
        super(TestMultiLog, self).setUp()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.patchOS(self.root)
        self.patchUtils(self.root)
        self.patchOpen(self.root)
        self.stdout = six.StringIO()
        self.stderr = six.StringIO()
        self.patchStdoutAndStderr(self.stdout, self.stderr)

    def test_stderr_used_by_default(self):
        logged_string = 'test stderr output'
        util.multi_log(logged_string)
        self.assertEqual(logged_string, self.stderr.getvalue())

    def test_stderr_not_used_if_false(self):
        util.multi_log('should not see this', stderr=False)
        self.assertEqual('', self.stderr.getvalue())

    def test_logs_go_to_console_by_default(self):
        self._createConsole(self.root)
        logged_string = 'something very important'
        util.multi_log(logged_string)
        self.assertEqual(logged_string, open('/dev/console').read())

    def test_logs_dont_go_to_stdout_if_console_exists(self):
        self._createConsole(self.root)
        util.multi_log('something')
        self.assertEqual('', self.stdout.getvalue())

    def test_logs_go_to_stdout_if_console_does_not_exist(self):
        logged_string = 'something very important'
        util.multi_log(logged_string)
        self.assertEqual(logged_string, self.stdout.getvalue())

    def test_logs_go_to_log_if_given(self):
        log = mock.MagicMock()
        logged_string = 'something very important'
        util.multi_log(logged_string, log=log)
        self.assertEqual([((mock.ANY, logged_string), {})],
                         log.log.call_args_list)

    def test_newlines_stripped_from_log_call(self):
        log = mock.MagicMock()
        expected_string = 'something very important'
        util.multi_log('{0}\n'.format(expected_string), log=log)
        self.assertEqual((mock.ANY, expected_string), log.log.call_args[0])

    def test_log_level_defaults_to_debug(self):
        log = mock.MagicMock()
        util.multi_log('message', log=log)
        self.assertEqual((logging.DEBUG, mock.ANY), log.log.call_args[0])

    def test_given_log_level_used(self):
        log = mock.MagicMock()
        log_level = mock.Mock()
        util.multi_log('message', log=log, log_level=log_level)
        self.assertEqual((log_level, mock.ANY), log.log.call_args[0])


class TestMessageFromString(helpers.TestCase):

    def test_unicode_not_messed_up(self):
        roundtripped = util.message_from_string(u'\n').as_string()
        self.assertNotIn('\x00', roundtripped)


class TestReadSeeded(helpers.TestCase):
    def setUp(self):
        super(TestReadSeeded, self).setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_unicode_not_messed_up(self):
        ud = b"userdatablob"
        helpers.populate_dir(
            self.tmp, {'meta-data': "key1: val1", 'user-data': ud})
        sdir = self.tmp + os.path.sep
        (found_md, found_ud) = util.read_seeded(sdir)

        self.assertEqual(found_md, {'key1': 'val1'})
        self.assertEqual(found_ud, ud)


class TestSubp(helpers.TestCase):

    stdin2err = ['bash', '-c', 'cat >&2']
    stdin2out = ['cat']
    utf8_invalid = b'ab\xaadef'
    utf8_valid = b'start \xc3\xa9 end'
    utf8_valid_2 = b'd\xc3\xa9j\xc8\xa7'
    printenv = ['bash', '-c', 'for n in "$@"; do echo "$n=${!n}"; done', '--']

    def printf_cmd(self, *args):
        # bash's printf supports \xaa.  So does /usr/bin/printf
        # but by using bash, we remove dependency on another program.
        return(['bash', '-c', 'printf "$@"', 'printf'] + list(args))

    def test_subp_handles_utf8(self):
        # The given bytes contain utf-8 accented characters as seen in e.g.
        # the "deja dup" package in Ubuntu.
        cmd = self.printf_cmd(self.utf8_valid_2)
        (out, _err) = util.subp(cmd, capture=True)
        self.assertEqual(out, self.utf8_valid_2.decode('utf-8'))

    def test_subp_respects_decode_false(self):
        (out, err) = util.subp(self.stdin2out, capture=True, decode=False,
                               data=self.utf8_valid)
        self.assertTrue(isinstance(out, bytes))
        self.assertTrue(isinstance(err, bytes))
        self.assertEqual(out, self.utf8_valid)

    def test_subp_decode_ignore(self):
        # this executes a string that writes invalid utf-8 to stdout
        (out, _err) = util.subp(self.printf_cmd('abc\\xaadef'),
                                capture=True, decode='ignore')
        self.assertEqual(out, 'abcdef')

    def test_subp_decode_strict_valid_utf8(self):
        (out, _err) = util.subp(self.stdin2out, capture=True,
                                decode='strict', data=self.utf8_valid)
        self.assertEqual(out, self.utf8_valid.decode('utf-8'))

    def test_subp_decode_invalid_utf8_replaces(self):
        (out, _err) = util.subp(self.stdin2out, capture=True,
                                data=self.utf8_invalid)
        expected = self.utf8_invalid.decode('utf-8', 'replace')
        self.assertEqual(out, expected)

    def test_subp_decode_strict_raises(self):
        args = []
        kwargs = {'args': self.stdin2out, 'capture': True,
                  'decode': 'strict', 'data': self.utf8_invalid}
        self.assertRaises(UnicodeDecodeError, util.subp, *args, **kwargs)

    def test_subp_capture_stderr(self):
        data = b'hello world'
        (out, err) = util.subp(self.stdin2err, capture=True,
                               decode=False, data=data,
                               update_env={'LC_ALL': 'C'})
        self.assertEqual(err, data)
        self.assertEqual(out, b'')

    def test_subp_reads_env(self):
        with mock.patch.dict("os.environ", values={'FOO': 'BAR'}):
            out, err = util.subp(self.printenv + ['FOO'], capture=True)
        self.assertEqual('FOO=BAR', out.splitlines()[0])

    def test_subp_env_and_update_env(self):
        out, err = util.subp(
            self.printenv + ['FOO', 'HOME', 'K1', 'K2'], capture=True,
            env={'FOO': 'BAR'},
            update_env={'HOME': '/myhome', 'K2': 'V2'})
        self.assertEqual(
            ['FOO=BAR', 'HOME=/myhome', 'K1=', 'K2=V2'], out.splitlines())

    def test_subp_update_env(self):
        extra = {'FOO': 'BAR', 'HOME': '/root', 'K1': 'V1'}
        with mock.patch.dict("os.environ", values=extra):
            out, err = util.subp(
                self.printenv + ['FOO', 'HOME', 'K1', 'K2'], capture=True,
                update_env={'HOME': '/myhome', 'K2': 'V2'})

        self.assertEqual(
            ['FOO=BAR', 'HOME=/myhome', 'K1=V1', 'K2=V2'], out.splitlines())

    def test_returns_none_if_no_capture(self):
        (out, err) = util.subp(self.stdin2out, data=b'', capture=False)
        self.assertIsNone(err)
        self.assertIsNone(out)

    def test_bunch_of_slashes_in_path(self):
        self.assertEqual("/target/my/path/",
                         util.target_path("/target/", "//my/path/"))
        self.assertEqual("/target/my/path/",
                         util.target_path("/target/", "///my/path/"))


class TestEncode(helpers.TestCase):
    """Test the encoding functions"""
    def test_decode_binary_plain_text_with_hex(self):
        blob = 'BOOTABLE_FLAG=\x80init=/bin/systemd'
        text = util.decode_binary(blob)
        self.assertEqual(text, blob)


class TestProcessExecutionError(helpers.TestCase):

    template = ('{description}\n'
                'Command: {cmd}\n'
                'Exit code: {exit_code}\n'
                'Reason: {reason}\n'
                'Stdout: {stdout}\n'
                'Stderr: {stderr}')
    empty_attr = '-'
    empty_description = 'Unexpected error while running command.'

    def test_pexec_error_indent_text(self):
        error = util.ProcessExecutionError()
        msg = 'abc\ndef'
        formatted = 'abc\n{0}def'.format(' ' * 4)
        self.assertEqual(error._indent_text(msg, indent_level=4), formatted)
        self.assertEqual(error._indent_text(msg.encode(), indent_level=4),
                         formatted.encode())
        self.assertIsInstance(
            error._indent_text(msg.encode()), type(msg.encode()))

    def test_pexec_error_type(self):
        self.assertIsInstance(util.ProcessExecutionError(), IOError)

    def test_pexec_error_empty_msgs(self):
        error = util.ProcessExecutionError()
        self.assertTrue(all(attr == self.empty_attr for attr in
                            (error.stderr, error.stdout, error.reason)))
        self.assertEqual(error.description, self.empty_description)
        self.assertEqual(str(error), self.template.format(
            description=self.empty_description, exit_code=self.empty_attr,
            reason=self.empty_attr, stdout=self.empty_attr,
            stderr=self.empty_attr, cmd=self.empty_attr))

    def test_pexec_error_single_line_msgs(self):
        stdout_msg = 'out out'
        stderr_msg = 'error error'
        cmd = 'test command'
        exit_code = 3
        error = util.ProcessExecutionError(
            stdout=stdout_msg, stderr=stderr_msg, exit_code=3, cmd=cmd)
        self.assertEqual(str(error), self.template.format(
            description=self.empty_description, stdout=stdout_msg,
            stderr=stderr_msg, exit_code=str(exit_code),
            reason=self.empty_attr, cmd=cmd))

    def test_pexec_error_multi_line_msgs(self):
        # make sure bytes is converted handled properly when formatting
        stdout_msg = 'multi\nline\noutput message'.encode()
        stderr_msg = 'multi\nline\nerror message\n\n\n'
        error = util.ProcessExecutionError(
            stdout=stdout_msg, stderr=stderr_msg)
        self.assertEqual(
            str(error),
            '\n'.join((
                '{description}',
                'Command: {empty_attr}',
                'Exit code: {empty_attr}',
                'Reason: {empty_attr}',
                'Stdout: multi',
                '        line',
                '        output message',
                'Stderr: multi',
                '        line',
                '        error message',
            )).format(description=self.empty_description,
                      empty_attr=self.empty_attr))


class TestSystemIsSnappy(helpers.FilesystemMockingTestCase):
    def test_id_in_os_release_quoted(self):
        """os-release containing ID="ubuntu-core" is snappy."""
        orcontent = '\n'.join(['ID="ubuntu-core"', ''])
        root_d = self.tmp_dir()
        helpers.populate_dir(root_d, {'etc/os-release': orcontent})
        self.reRoot(root_d)
        self.assertTrue(util.system_is_snappy())

    def test_id_in_os_release(self):
        """os-release containing ID=ubuntu-core is snappy."""
        orcontent = '\n'.join(['ID=ubuntu-core', ''])
        root_d = self.tmp_dir()
        helpers.populate_dir(root_d, {'etc/os-release': orcontent})
        self.reRoot(root_d)
        self.assertTrue(util.system_is_snappy())

    @mock.patch('cloudinit.util.get_cmdline')
    def test_bad_content_in_os_release_no_effect(self, m_cmdline):
        """malformed os-release should not raise exception."""
        m_cmdline.return_value = 'root=/dev/sda'
        orcontent = '\n'.join(['IDubuntu-core', ''])
        root_d = self.tmp_dir()
        helpers.populate_dir(root_d, {'etc/os-release': orcontent})
        self.reRoot()
        self.assertFalse(util.system_is_snappy())

    @mock.patch('cloudinit.util.get_cmdline')
    def test_snap_core_in_cmdline_is_snappy(self, m_cmdline):
        """The string snap_core= in kernel cmdline indicates snappy."""
        cmdline = (
            "BOOT_IMAGE=(loop)/kernel.img root=LABEL=writable "
            "snap_core=core_x1.snap snap_kernel=pc-kernel_x1.snap ro "
            "net.ifnames=0 init=/lib/systemd/systemd console=tty1 "
            "console=ttyS0 panic=-1")
        m_cmdline.return_value = cmdline
        self.assertTrue(util.system_is_snappy())
        self.assertTrue(m_cmdline.call_count > 0)

    @mock.patch('cloudinit.util.get_cmdline')
    def test_nothing_found_is_not_snappy(self, m_cmdline):
        """If no positive identification, then not snappy."""
        m_cmdline.return_value = 'root=/dev/sda'
        self.reRoot()
        self.assertFalse(util.system_is_snappy())
        self.assertTrue(m_cmdline.call_count > 0)

    @mock.patch('cloudinit.util.get_cmdline')
    def test_channel_ini_with_snappy_is_snappy(self, m_cmdline):
        """A Channel.ini file with 'ubuntu-core' indicates snappy."""
        m_cmdline.return_value = 'root=/dev/sda'
        root_d = self.tmp_dir()
        content = '\n'.join(["[Foo]", "source = 'ubuntu-core'", ""])
        helpers.populate_dir(
            root_d, {'etc/system-image/channel.ini': content})
        self.reRoot(root_d)
        self.assertTrue(util.system_is_snappy())

    @mock.patch('cloudinit.util.get_cmdline')
    def test_system_image_config_dir_is_snappy(self, m_cmdline):
        """Existence of /etc/system-image/config.d indicates snappy."""
        m_cmdline.return_value = 'root=/dev/sda'
        root_d = self.tmp_dir()
        helpers.populate_dir(
            root_d, {'etc/system-image/config.d/my.file': "_unused"})
        self.reRoot(root_d)
        self.assertTrue(util.system_is_snappy())

# vi: ts=4 expandtab
