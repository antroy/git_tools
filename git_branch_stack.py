#!/usr/bin/env python3

from subprocess import run, STDOUT, PIPE
import argparse
import json
import os
import re
from select import select
import sys


def dump(data):
    try:
        import yaml
        return yaml.dump(data, default_flow_style=False)
    except ModuleNotFoundError:
        return json.dumps(data)


def load(fh):
    try:
        import yaml
        return yaml.safe_load(fh)
    except ModuleNotFoundError:
        return json.load(fh)


def i_print(verbose, message):
    if verbose:
        print(message)


def _col(code, s):
    return "\033[%sm%s\033[0m" % (code, s)


class Git:
    def __init__(self, verbose):
        self.verbose = verbose

    def root(self):
        return self._run(["git", "rev-parse", "--show-toplevel"])

    def branches(self):
        result = self._run(["git", "branch", "--all", "--no-color"]).split("\n")

        out = [b[1:].strip() for b in result if "origin/HEAD" not in b]
        out = set(re.sub("remotes/origin/", "", branch) for branch in out)

        return out

    def remotes_for_local_branches(self):
        results = [r.split('&') for r in self._run([
            "git", "for-each-ref",
            '--format=%(refname:short)&%(upstream:short)',
            "refs/heads"
        ]).split("\n")]

        return {r[0]: r[1] for r in results}

    def statuses(self):
        mapping = self.remotes_for_local_branches()

        return {loc: self.status_for(loc, rem) for loc, rem in mapping.items()}

    def status_for(self, local, remote):
        query = "%s...%s" % (remote, local)
        revs = self._run(["git", "rev-list", "--left-right", query]).split("\n")
        behind = len([1 for r in revs if r.startswith("<")])
        ahead = len([1 for r in revs if r.startswith(">")])

        behind_str = "<%s" % behind if behind else ""
        ahead_str = ">%s" % ahead if ahead else ""
        out = "%s%s" % (behind_str, ahead_str)

        return out if out else "="

    def current_branch(self):
        result = self._run(["git", "branch", "--no-color"]).split("\n")
        out = [r[1:].strip() for r in result if r.startswith("*")][0]
        return re.sub(r"\(HEAD detached at (.*)\)", r"\1", out)

    def checkout(self, params, branch=None):
        parameters = ["git", "checkout"]
        parameters += params
        if branch:
            parameters += [branch]

        return self._run_with_status(parameters)

    def ref_exists(self, branch):
        remote_ref = "origin/%s" % branch
        return self._ref_exists(branch) or self._ref_exists(remote_ref)

    def _ref_exists(self, branch):
        cmd = ["git", "branch", "--no-color"]
        return self._run_with_status(cmd).returncode == 0

    def _run(self, args):
        return self._run_with_status(args).stdout.strip()

    def _run_with_status(self, args):
        i_print(self.verbose, "Running: '%s'" % " ".join(args if args else []))
        return run(args, stdout=PIPE, stderr=STDOUT, encoding="utf-8")


class Stack:
    def __init__(self, stack_file, verbose):
        self.verbose = verbose

        try:
            with open(stack_file) as fh:
                stack_dict = load(fh)
        except Exception:
            stack_dict = {}

        self.git = Git(verbose)
        root = self.git.root()

        self.stack_file = stack_file
        self.stack_dict = stack_dict
        i_print(verbose, "Saving: %s" % dump(stack_dict))

        if root not in stack_dict:
            stack_dict[root] = {'ring': [], 'position': None}
        self.stack = stack_dict[root]

    def is_empty(self):
        return self.ring is None or len(self.ring) == 0

    @property
    def ring(self):
        return self.stack['ring']

    @ring.setter
    def ring(self, new_ring):
        self.stack['ring'] = new_ring

    @property
    def index(self):
        return self.stack['position']

    @index.setter
    def index(self, index):
        self.stack['position'] = index

    def save(self):
        if self.verbose:
            self.print_ring()

        data = dump(self.stack_dict)

        with open(self.stack_file, "w") as fh:
            fh.write(data)

    def print_ring(self):
        statuses = self.git.statuses()

        for i, ref in enumerate(self.ring):
            status = statuses[ref] if ref in statuses else ""

            to_print = "%s) %-20s %s" % (i + 1, ref, status)

            if i == self.index:
                to_print = (_col(32, to_print))

            print(to_print)

    def push(self, branch):
        if branch in self.ring:
            new_position = self.ring.index(branch)
        else:
            new_position = self.index + 1 if self.index is not None else 0
            self.ring.insert(new_position, branch)
        self.index = new_position
        self.save()

    def pop(self):
        if self.index is None:
            print("No branches on the stack")
            sys.exit(1)

        out = self.ring[self.index]
        del self.ring[self.index]

        if self.ring:
            self.index = (self.index - 1) % len(self.ring)
        else:
            self.index = None

        self.save()
        return out

    def current(self):
        if self.ring:
            if len(self.ring) > self.index:
                return self.ring[self.index]

        return None

    def back(self):
        if not self.ring:
            return None

        new_index = (self.index - 1) % len(self.ring)
        self.index = new_index
        self.save()
        return self.ring[new_index]

    def forward(self):
        if not self.ring:
            return None

        new_index = (self.index + 1) % len(self.ring)
        self.index = new_index
        self.save()
        return self.ring[new_index]


def opts():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'command',
        type=str,
        choices=['push', 'pop', 'next', 'prev', 'test', 'curr', 'ring', 'clean']
    )
    parser.add_argument('args', nargs='*')
    parser.add_argument('-t', '--timeout', type=int, default=10)
    parser.add_argument('-v', '--verbose', action='store_true', default=False)

    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except Exception:
        pass

    out = parser.parse_args()

    config_dir = os.path.expanduser("~/.config")
    stack_file = os.path.join(config_dir, "gitstack")

    if not os.path.isdir(config_dir):
        os.makedirs(config_dir)

    out.stack_file = stack_file

    return out


def _fix_ring(stack, branch, opts):
    expected_branch = stack.current()

    git = Git(opts.verbose)

    stack.ring = [ref for ref in stack.ring if git.ref_exists(ref)]

    if stack.is_empty() or branch != expected_branch:
        stack.push(branch)

    stack.save()


def _prepare(opts):
    git = Git(opts.verbose)
    stack = Stack(opts.stack_file, opts.verbose)

    branch = git.current_branch()
    _fix_ring(stack, branch, opts)

    return git, stack, branch


def _cleanup(stack, code, branch, original_branch, opts, print_only=True):
    if code != 0:
        templ = "Looks like %s no longer exists. Cleaned up - please re-select."
        print(_col(33, templ % branch))
        stack.ring.remove(branch)
        _fix_ring(stack, original_branch, opts)
        print()
        print_ring(opts, print_only)
    else:
        print_ring(opts)


def push(opts):
    git, stack, branch = _prepare(opts)
    push_params = opts.args

    git.checkout(push_params)
    new_branch = git.current_branch()
    if not new_branch == branch:
        stack.push(new_branch)


def pop(opts):
    git, stack, branch = _prepare(opts)

    old_branch = stack.pop()
    new_branch = stack.current()

    i_print(opts.verbose, "Old: %s; New: %s" % (old_branch, new_branch))

    if new_branch:
        git.checkout([], new_branch)


def next_branch(opts):
    git, stack, branch = _prepare(opts)

    next_branch = stack.forward()

    if not next_branch:
        i_print(opts.verbose, "No branches in the ring")
        return

    i_print(opts.verbose, "B: %s" % next_branch)
    code = git.checkout([], next_branch).returncode

    _cleanup(stack, code, next_branch, branch, opts)


def prev_branch(opts):
    git, stack, branch = _prepare(opts)

    previous = stack.back()

    if not previous:
        i_print(opts.verbose, "No branches in the ring")
        return

    i_print(opts.verbose, "B: %s" % previous)
    code = git.checkout([], previous).returncode

    _cleanup(stack, code, previous, branch, opts)


def print_ring(opts, print_only=True):
    git, stack, branch = _prepare(opts)

    stack.print_ring()
    if print_only:
        return

    print("Type a number to switch to another branch")
    try:
        rlist, _, _ = select([sys.stdin], [], [], opts.timeout)
        if not rlist:
            return

        resp = sys.stdin.readline().strip()
        if not resp:
            return

        m = re.match(r"(?i)(d?)( *\d+(?: +\d+)*)", resp)
        action = m.group(1).lower()
        branches = [stack.ring[int(b) - 1] for b in m.group(2).strip().split()]

        if action == 'd':
            for branch_i in branches:
                if branch == branch_i:
                    print("Popping %s" % branch_i)
                    pop(opts)
                else:
                    print("Deleting %s" % branch_i)
                    stack.ring.remove(branch_i)
                    stack.save()

            return

        branch_i = branches[0]
        if branch == branch_i:
            return

        print("Checking out %s" % branch_i)
        code = git.checkout([branch_i]).returncode
        if code != 0:
            _cleanup(stack, code, branch_i, branch, opts, print_only)
        new_branch = git.current_branch()

        if not new_branch == branch:
            stack.push(new_branch)
    except Exception as ex:
        pass


def remove_missing_branches(opts):
    git, stack, branch = _prepare(opts)

    valid_branches = set(stack.ring).intersection(git.branches())
    stack.ring = [br for br in stack.ring if br in valid_branches]

    _fix_ring(stack, branch, opts)
    print_ring(opts)


class Test:
    def __init__(self):
        import datetime
        print("\nTesting Ring Stack [%s]" % datetime.datetime.now())

    def run(self):
        import tempfile
        temp_file = tempfile.NamedTemporaryFile("w", delete=False)
        self.filename = temp_file.name
        temp_file.close()

        for m in [m for m in dir(self) if m.startswith("test_")]:
            self.setup()

            try:
                getattr(self, m)()
                print("%s - OK" % m)
            except Exception as ex:
                print("%s - FAIL: %s" % (m, ex))
                import traceback
                traceback.print_exc()

            try:
                self.teardown()
            except Exception:
                pass

    def setup(self):
        self.stack = Stack(self.filename, False)

    def teardown(self):
        os.remove(self.filename)

    def test_stack_push_pop(self):
        self.stack.push("bob")
        assert self.stack.pop() == "bob", "Pushed value is popped"
        try:
            self.stack.pop()
            assert False, "Should error if popping an empty ring"
        except SystemExit:
            pass

    def test_stack_push_doesnt_add_duplicates(self):
        self.stack.push('bob')
        self.stack.push('bob')
        assert self.stack.pop() == "bob", "Bob is on the stack"
        try:
            self.stack.pop()
            assert False, "But only once"
        except SystemExit:
            pass

    def test_stack_current_reports_correct_place(self):
        assert self.stack.current() is None
        self.stack.push('aaa')
        assert self.stack.current() == "aaa"
        self.stack.push('bbb')
        assert self.stack.current() == "bbb"
        self.stack.pop()
        assert self.stack.current() == "aaa"
        self.stack.pop()
        assert self.stack.current() is None

    def test_stack_back_cycles_back_through_ring(self):
        self.stack.push('aaa')
        self.stack.push('bbb')
        self.stack.push('ccc')

        assert self.stack.current() == "ccc"

        assert self.stack.back() == "bbb"
        assert self.stack.current() == "bbb"

        assert self.stack.back() == "aaa"
        assert self.stack.current() == "aaa"

        assert self.stack.back() == "ccc"
        assert self.stack.current() == "ccc"

    def test_stack_forward_cycles_forward_through_ring(self):
        self.stack.push('aaa')
        self.stack.push('bbb')
        self.stack.push('ccc')

        assert self.stack.current() == "ccc"

        assert self.stack.forward() == "aaa"
        assert self.stack.current() == "aaa"

        assert self.stack.forward() == "bbb"
        assert self.stack.current() == "bbb"

        assert self.stack.forward() == "ccc"
        assert self.stack.current() == "ccc"

    def test_stack_jumping_and_popping(self):
        self.stack.push('aaa')
        self.stack.push('bbb')
        self.stack.push('ccc')

        assert self.stack.current() == "ccc"

        assert self.stack.forward() == "aaa"
        assert self.stack.forward() == "bbb"
        assert self.stack.current() == "bbb"

        assert self.stack.pop() == "bbb"
        assert self.stack.current() == "aaa"

        assert self.stack.back() == "ccc"
        assert self.stack.current() == "ccc"

        assert self.stack.pop() == "ccc"
        assert self.stack.current() == "aaa"

        self.stack.push("ddd")
        assert self.stack.current() == "ddd"
        assert self.stack.forward() == "aaa"

    def test_stack_popping_from_head(self):
        self.stack.push('aaa')
        self.stack.push('bbb')
        self.stack.push('ccc')

        assert self.stack.back() == "bbb"
        assert self.stack.back() == "aaa"
        assert self.stack.pop() == "aaa"
        assert self.stack.current() == "ccc"

    def test_move_in_empty_ring(self):
        assert self.stack.forward() is None
        assert self.stack.back() is None

    def test_move_in_singleton_ring(self):
        self.stack.push("aaa")
        assert self.stack.forward() == "aaa"
        assert self.stack.back() == "aaa"


if __name__ == "__main__":
    options = opts()
    if options.command == 'push':
        push(options)
    if options.command == 'pop':
        pop(options)
    if options.command == 'next':
        next_branch(options)
    if options.command == 'prev':
        prev_branch(options)
    if options.command == 'ring':
        print_ring(options, False)
    if options.command == 'clean':
        remove_missing_branches(options)
    if options.command == 'test':
        Test().run()
