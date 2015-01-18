#    Copyright 2014 Red Hat Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from nova import db
from nova import exception
from nova.objects import base
from nova.objects import fields
from nova.openstack.common import jsonutils
from nova.virt import hardware


class InstanceNUMACell(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Add pagesize field
    VERSION = '1.1'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'cpuset': fields.SetOfIntegersField(),
        'memory': fields.IntegerField(),
        'pagesize': fields.IntegerField(nullable=True),
        }


class InstanceNUMATopology(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Takes into account pagesize
    VERSION = '1.1'

    fields = {
        # NOTE(danms): The 'id' field is no longer used and should be
        # removed in the future when convenient
        'id': fields.IntegerField(),
        'instance_uuid': fields.UUIDField(),
        'cells': fields.ListOfObjectsField('InstanceNUMACell'),
        }

    @classmethod
    def obj_from_db_obj(cls, instance_uuid, db_obj):
        if 'nova_object.name' in db_obj:
            obj_topology = cls.obj_from_primitive(
                jsonutils.loads(db_obj))
        else:
            # NOTE(sahid): This compatibility code needs to stay until we can
            # guarantee that there are no cases of the old format stored in
            # the database (or forever, if we can never guarantee that).
            topo = hardware.VirtNUMAInstanceTopology.from_json(db_obj)
            obj_topology = cls.obj_from_topology(topo)
            obj_topology.instance_uuid = instance_uuid

            # No benefit to store a list of changed fields
            obj_topology.obj_reset_changes()
        return obj_topology

    @classmethod
    def obj_from_topology(cls, topology):
        if not isinstance(topology, hardware.VirtNUMAInstanceTopology):
            raise exception.ObjectActionError(action='obj_from_topology',
                                              reason='invalid topology class')
        if topology:
            cells = []
            for topocell in topology.cells:
                cell = InstanceNUMACell(id=topocell.id, cpuset=topocell.cpuset,
                                        memory=topocell.memory,
                                        pagesize=topocell.pagesize)
                cells.append(cell)
            return cls(cells=cells)

    def topology_from_obj(self):
        cells = []
        for objcell in self.cells:
            cell = hardware.VirtNUMATopologyCellInstance(
                objcell.id, objcell.cpuset, objcell.memory, objcell.pagesize)
            cells.append(cell)
        return hardware.VirtNUMAInstanceTopology(cells=cells)

    # TODO(ndipanov) Remove this method on the major version bump to 2.0
    @base.remotable
    def create(self, context):
        self._save(context)

    # NOTE(ndipanov): We can't rename create and want to avoid version bump
    # as this needs to be backported to stable so this is not a @remotable
    # That's OK since we only call it from inside Instance.save() which is.
    def _save(self, context):
        values = {'numa_topology': self._to_json()}
        db.instance_extra_update_by_uuid(context, self.instance_uuid,
                                         values)
        self.obj_reset_changes()

    # NOTE(ndipanov): We want to avoid version bump
    # as this needs to be backported to stable so this is not a @remotable
    # That's OK since we only call it from inside Instance.save() which is.
    @classmethod
    def delete_by_instance_uuid(cls, context, instance_uuid):
        values = {'numa_topology': None}
        db.instance_extra_update_by_uuid(context, instance_uuid,
                                         values)

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_extra = db.instance_extra_get_by_instance_uuid(
                context, instance_uuid, columns=['numa_topology'])
        if not db_extra:
            raise exception.NumaTopologyNotFound(instance_uuid=instance_uuid)

        if db_extra['numa_topology'] is None:
            return None

        return cls.obj_from_db_obj(instance_uuid, db_extra['numa_topology'])

    def _to_json(self):
        return jsonutils.dumps(self.obj_to_primitive())
