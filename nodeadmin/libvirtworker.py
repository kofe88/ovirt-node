# libvirtworker.py - Copyright (C) 2009 Red Hat, Inc.
# Written by Darryl L. Pierce <dpierce@redhat.com>
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

import dbus
import libvirt
import os
import virtinst
import utils

from domainconfig import DomainConfig

DEFAULT_POOL_TARGET_PATH="/var/lib/libvirt/images"

class LibvirtWorker:
    '''Provides utilities for interfacing with libvirt.'''
    def __init__(self, url = "qemu:///system"):
        self.__conn = libvirt.open(url)
        self.__capabilities = virtinst.CapabilitiesParser.parse(self.__conn.getCapabilities())
        self.__net = virtinst.VirtualNetworkInterface(conn = self.__conn)
        self.__net.setup(self.__conn)
        (self.__new_guest, self.__new_domain) = virtinst.CapabilitiesParser.guest_lookup(conn = self.__conn)

    def list_domains(self, defined = True, started = True):
        '''Lists all domains.'''
        result = []
        if defined:
            result.extend(self.__conn.listDefinedDomains())
        if started:
            for id in self.__conn.listDomainsID():
                result.append(self.__conn.lookupByID(id).name())
        return result

    def get_domain(self, name):
        '''Returns the specified domain.'''
        result = self.__conn.lookupByName(name)
        if result is None: raise Exception("No such domain exists: %s" % name)

        return result

    def domain_exists(self, name):
        '''Returns whether a domain with the specified node exists.'''
        domains = self.list_domains()
        if name in domains: return True
        return False

    def create_domain(self, name):
        '''Creates the specified domain.'''
        domain = self.get_domain(name)
        domain.create()

    def destroy_domain(self, name):
        '''Destroys the specified domain.'''
        domain = self.get_domain(name)
        domain.destroy()

    def undefine_domain(self, name):
        '''Undefines the specified domain.'''
        domain = self.get_domain(name)
        domain.undefine()

    def list_storage_pools(self):
        '''Returns the list of all defined storage pools.'''
        return self.__conn.listStoragePools()

    def storage_pool_exists(self, name):
        '''Returns whether a storage pool exists.'''
        pools = self.list_storage_pools()
        if name in pools: return True
        return False

    def define_storage_pool(self, name):
        '''Defines a storage pool with the given name.'''
        try:
            pool = virtinst.Storage.DirectoryPool(conn=self.__conn,
                                                  name=name,
                                                  target_path=DEFAULT_POOL_TARGET_PATH)
            newpool = pool.install(build=True, create=True)
            newpool.setAutostart(True)
        except Exception, error:
            raise RuntimeError("Could not create pool: %s - %s", str(error))

    def list_bridges(self):
        '''Lists all defined and active bridges.'''
        bridges = self.__conn.listNetworks()
        bridges.extend(self.__conn.listDefinedNetworks())
        result = []
        for name in bridges:
            bridge = self.__conn.networkLookupByName(name)
            result.append(bridge)
        return result

    def generate_mac_address(self):
        return self.__net.macaddr

    def list_storage_volumes(self):
        '''Lists all defined storage volumes.'''
        pools = self.__conn.listStoragePools()
        pools.extend(self.__conn.listDefinedStoragePools())
        result = []
        for name in pools:
            pool = self.__conn.storagePoolLookupByName(name)
            for volname in pool.listVolumes():
                volume = self.__conn.storageVolLookupByPath("/var/lib/libvirt/images/%s" % volname)
                result.append(volume)
        return result

    def get_storage_size(self, name):
        '''Returns the size of the specified storage volume.'''
        volume = self.__conn.storageVolLookupByPath("/var/lib/libvirt/images/%s" % name)
        return volume.info()[1] / (1024.0 ** 3)

    def get_virt_types(self):
        result = []
        for guest in self.__capabilities.guests:
            guest_type = guest.os_type
            for domain in guest.domains:
                domain_type = domain.hypervisor_type
                label = domain_type

                if domain_type is "kvm" and guest_type is "xen": label = "xenner"
                elif domain_type is "xen":
                    if guest_type is "xen":
                        label = "xen (paravirt)"
                    elif guest_type is "kvm":
                        label = "xen (fullvirt)"
                elif domain_type is "test":
                    if guest_type is "xen":
                        label = "test (xen)"
                    elif guest_type is "hvm":
                        label = "test (hvm)"

                for row in result:
                    if row[0] == label:
                        label = None
                        break
                if label is None: continue

                result.append([label, domain_type, guest_type])
        return result

    def list_virt_types(self):
        virt_types = self.get_virt_types()
        result = []
        for type in virt_types:
            result.append(type[0])
        return result

    def get_default_architecture(self):
        '''Returns a default hypervisor type for new domains.'''
        return self.__new_guest.arch

    def get_hypervisor(self, virt_type):
        virt_types = self.get_virt_types()
        for type in virt_types:
            if type[0] is virt_type: return type[1]
        return None

    def get_default_virt_type(self):
        '''Returns the default virtualization type for new domains.'''
        return self.__new_domain.hypervisor_type

    def get_os_type(self, virt_type):
        virt_types = self.get_virt_types()
        for type in virt_types:
            if type[0] is virt_type: return type[2]
        return None

    def list_architectures(self):
        result = []
        for guest in self.__capabilities.guests:
            for domain in guest.domains:
                label = guest.arch
                for row in result:
                    if row == label:
                        label = None
                        break
                if label is None: continue

                result.append(label)
        return result

    def define_domain(self, config, meter):
        location = extra = kickstart = None

        if config.get_install_type() == DomainConfig.LOCAL_INSTALL:
            if config.get_use_cdrom_source():
                iclass = virtinst.DistroInstaller
                location = config.get_install_media()
            else:
                iclass = virtinst.LiveCDInstaller
                location = config.get_iso_path()
        elif config.get_install_type() == DomainConfig.NETWORK_INSTALL:
            iclass = virtinst.DistroInstaller
            location = config.get_install_url()
            extra = config.get_kernel_options()
            kickstart = config.get_kickstart_url()
        elif config.get_install_type() == DomainConfig.PXE_INSTALL:
            iclass = virtinst.PXEInstaller

        installer = iclass(conn = self.__conn,
                           type = self.get_hypervisor(config.get_virt_type()),
                           os_type = self.get_os_type(config.get_virt_type()))
        self.__guest = installer.guest_from_installer()
        self.__guest.name = config.get_guest_name()
        self.__guest.vcpus = config.get_cpus()
        self.__guest.memory = config.get_memory()
        self.__guest.maxmemory = config.get_memory()

        self.__guest.installer.location = location
        if config.get_use_cdrom_source(): self.__guest.installer.cdrom = True
        extraargs = ""
        if extra: extraargs += extra
        if kickstart: extraargs += " ks=%s" % kickstart
        if extraargs: self.__guest.installer.extraarags = extraargs

        self.__guest.uuid = virtinst.util.uuidToString(virtinst.util.randomUUID())

        if config.get_os_type() != "generic": self.__guest.os_type = config.get_os_type()
        if config.get_os_variant() != "generic": self.__guest.os_variant = config.get_os_variant()

        self.__guest._graphics_dev = virtinst.VirtualGraphics(type = virtinst.VirtualGraphics.TYPE_VNC)
        self.__guest.sound_devs = []
        self.__guest.sound_devs.append(virtinst.VirtualAudio(model = "es1370"))

        self._setup_nics(config)
        self._setup_disks(config)

        self.__guest.conn = self.__conn
        self.__domain = self.__guest.start_install(False, meter = meter)

    def _setup_nics(self, config):
        self.__guest.nics = []
        nic = virtinst.VirtualNetworkInterface(type = virtinst.VirtualNetworkInterface.TYPE_VIRTUAL,
                                               bridge = config.get_network_bridge(),
                                               network = config.get_network_bridge(),
                                               macaddr = config.get_mac_address())
        self.__guest.nics.append(nic)
        # ensure the network is running
        if config.get_network_bridge() not in self.__conn.listNetworks():
            network = self.__conn.networkLookupByName(config.get_network_bridge())
            network.create()

    def _setup_disks(self, config):
        self.__guest.disks = []
        if config.get_enable_storage():
            path = None
            if config.get_use_local_storage():
                if self.storage_pool_exists("default") is False:
                    self.define_storage_pool("default")
                pool = self.__conn.storagePoolLookupByName("default")
                path = virtinst.Storage.StorageVolume.find_free_name(config.get_guest_name(),
                                                                     pool_object = pool,
                                                                     suffix = ".img")
                path = os.path.join(DEFAULT_POOL_TARGET_PATH, path)

            if path is not None:
                storage= virtinst.VirtualDisk(conn = self.__conn,
                                              path = path,
                                              size = config.get_storage_size())
                self.__guest.disks.append(storage)
        self.__guest.conn = self.__conn
