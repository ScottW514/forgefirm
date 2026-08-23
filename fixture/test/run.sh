#!/bin/sh
# The host test of the fixture's policy: needs only a C compiler.
set -e
cd "$(dirname "$0")"
${CC:-cc} -std=c11 -Wall -Wextra -Werror -o policy_test policy_test.c ../main/policy.c
./policy_test
