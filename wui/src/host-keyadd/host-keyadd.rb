#!/usr/bin/ruby
# 
# Copyright (C) 2008 Red Hat, Inc.
# Written by Chris Lalancette <clalance@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA  02110-1301, USA.  A copy of the GNU General Public License is
# also available at http://www.gnu.org/copyleft/gpl.html.

require 'socket'
require 'rubygems'
require 'krb5_auth'
include Krb5Auth
require 'optparse'
require 'daemons'
include Daemonize

$logfile = '/var/log/ovirt-wui/host-keyadd.log'

def kadmin_local(command)
  # FIXME: we should check the return value from the system() call and throw
  # an exception.
  # FIXME: we need to return the output back to the caller here
  system("/usr/kerberos/sbin/kadmin.local -q '" + command + "'")
end

do_daemon = true
opts = OptionParser.new do |opts|
  opts.on("-h", "--help", "Print help message") do
    puts opts
    exit
  end
  opts.on("-n", "--nodaemon", "Run interactively (useful for debugging)") do |n|
    do_daemon = !n
  end
end
begin
  opts.parse!(ARGV)
rescue OptionParser::InvalidOption
  puts opts
  exit
end

if do_daemon
  daemonize
  STDOUT.reopen $logfile, 'a'
  STDERR.reopen STDOUT
end

server = TCPServer.new(6666)

loop do
  Thread.start(server.accept) do |s|
    cmd = s.read(4)
    if cmd.length != 4 or cmd != "KERB"
      s.write("FAILED")
    else
      remote = Socket.unpack_sockaddr_in(s.getpeername)
      remote_name = Socket.getnameinfo(s.getpeername)
      
      krb5 = Krb5.new
      default_realm = krb5.get_default_realm
      
      libvirt_princ = 'libvirt/' + remote_name[0] + '@' + default_realm
      
      outname = '/usr/share/ipa/html/' + remote[1] + '-libvirt.tab'
      
      kadmin_local('addprinc -randkey ' + libvirt_princ)
      kadmin_local('ktadd -k ' + outname + ' ' + libvirt_princ)
      File.chmod(0644, outname)
      s.write('SUCCESS')
    end
    s.close
  end
end
