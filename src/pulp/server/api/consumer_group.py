#!/usr/bin/python
#
# Copyright (c) 2010 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public License,
# version 2 (GPLv2). There is NO WARRANTY for this software, express or
# implied, including the implied warranties of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. You should have received a copy of GPLv2
# along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
#
# Red Hat trademarks are not licensed under GPLv2. No permission is
# granted to use or replicate Red Hat trademarks that are incorporated
# in this software or its documentation.

import logging

from pulp.server.agent import Agent
from pulp.server.api.base import BaseApi
from pulp.server.api.consumer import ConsumerApi
from pulp.server.api.repo import RepoApi
from pulp.server.auditing import audit
from pulp.server.db import model
from pulp.server.db.connection import get_object_db
from pulp.server.pexceptions import PulpException

log = logging.getLogger(__name__)


class ConsumerGroupApi(BaseApi):

    def __init__(self):
        BaseApi.__init__(self)
        self.consumerApi = ConsumerApi()
        self.repoApi = RepoApi()

    def _getcollection(self):
        return get_object_db('consumergroups',
                             self._unique_indexes,
                             self._indexes)


    @audit(params=['id', 'consumerids'])
    def create(self, id, description, consumerids=()):
        """
        Create a new ConsumerGroup object and return it
        """
        consumergroup = self.consumergroup(id)
        if(consumergroup):
            raise PulpException("A Consumer Group with id %s already exists" % id)
        
        for consumerid in consumerids:
            consumer = self.consumerApi.consumer(consumerid)
            if (consumer is None):
                raise PulpException("No Consumer with id: %s found" % consumerid)
                
        c = model.ConsumerGroup(id, description, consumerids)
        self.insert(c)
        return c


    def consumergroups(self):
        """
        List all consumergroups.
        """
        consumergroups = list(self.objectdb.find())
        return consumergroups

    def consumergroup(self, id):
        """
        Return a single ConsumerGroup object
        """
        return self.objectdb.find_one({'id': id})


    def consumers(self, id):
        """
        Return consumer ids belonging to this ConsumerGroup
        """
        consumer = self.objectdb.find_one({'id': id})
        return consumer['consumerids']


    @audit()
    def add_consumer(self, groupid, consumerid):
        """
        Adds the passed in consumer to this group
        """
        consumergroup = self.consumergroup(groupid)
        if (consumergroup is None):
            raise PulpException("No Consumer Group with id: %s found" % groupid)
        consumer = self.consumerApi.consumer(consumerid)
        if (consumer is None):
            raise PulpException("No Consumer with id: %s found" % consumerid)
        self._add_consumer(consumergroup, consumer)
        self.update(consumergroup)

    def _add_consumer(self, consumergroup, consumer):
        """
        Responsible for properly associating a Consumer to a ConsumerGroup
        """
        consumerids = consumergroup['consumerids']
        if consumer["id"] in consumerids:
            return
        
        consumerids.append(consumer["id"])
        consumergroup["consumerids"] = consumerids

    @audit()
    def delete_consumer(self, groupid, consumerid):
        consumergroup = self.consumergroup(groupid)
        if (consumergroup is None):
            raise PulpException("No Consumer Group with id: %s found" % groupid)
        consumerids = consumergroup['consumerids']
        if consumerid not in consumerids:
            return
        consumerids.remove(consumerid)
        consumergroup["consumerids"] = consumerids
        self.update(consumergroup)

    @audit()
    def bind(self, id, repoid):
        """
        Bind (subscribe) a consumer group to a repo.
        @param id: A consumer group id.
        @type id: str
        @param repoid: A repo id to bind.
        @type repoid: str
        @raise PulpException: When consumer group is not found.
        """
        consumergroup = self.consumergroup(id)
        if consumergroup is None:
            raise PulpException("No Consumer Group with id: %s found" % id)
        repo = self.repoApi.repository(repoid)
        if repo is None:
            raise PulpException("No Repository with id: %s found" % repoid)

        consumerids = consumergroup['consumerids']
        for consumerid in consumerids:
            self.consumerApi.bind(consumerid, repoid)

    @audit()
    def unbind(self, id, repoid):
        """
        Unbind (unsubscribe) a consumer group from a repo.
        @param id: A consumer group id.
        @type id: str
        @param repoid: A repo id to unbind.
        @type repoid: str
        @raise PulpException: When consumer group not found.
        """
        consumergroup = self.consumergroup(id)
        if consumergroup is None:
            raise PulpException("No Consumer Group with id: %s found" % id)
        repo = self.repoApi.repository(repoid)
        if (repo is None):
            raise PulpException("No Repository with id: %s found" % repoid)

        consumerids = consumergroup['consumerids']
        for consumerid in consumerids:
            self.consumerApi.unbind(consumerid, repoid)
            
            
    @audit()
    def installpackages(self, id, packagenames=[]):
        """
        Install packages on the consumers in a consumer group.
        @param id: A consumer group id.
        @type id: str
        @param packagenames: The package names to install.
        @type packagenames: [str,..]
        """
        consumergroup = self.consumergroup(id)
        if consumergroup is None:   
            raise PulpException("No Consumer Group with id: %s found" % id)
        consumerids = consumergroup['consumerids']
        for consumerid in consumerids:
            agent = Agent(consumerid)
            agent.packages.install(packagenames)
        return packagenames
    
    def installerrata(self, id, errataids=[], types=[]):
        """
        Install errata on a consumer group.
        @param id: A consumergroup id.
        @type id: str
        @param errataids: The errata ids to install.
        @type errataids: [str,..]
        @param types: Errata type filter
        @type types: str
        """
        consumergroup = self.consumergroup(id)
        if consumergroup is None:   
            raise PulpException("No Consumer Group with id: %s found" % id)
        consumerids = consumergroup['consumerids']
        consumer_pkg = {}
        for consumerid in consumerids:
            consumer = self.consumerApi.consumer(consumerid)
            agent = Agent(consumerid)
            pkgs = []
            if errataids:
                applicable_errata = self.consumerApi._applicable_errata(consumer, types)
                for eid in errataids:
                    for pobj in applicable_errata[eid]:
                        if pobj["arch"] != "src":
                            pkgs.append(pobj["name"]) # + "." + pobj["arch"])
            else:
                #apply all updates
                pkgobjs = self.consumerApi.list_package_updates(id, types)
                for pobj in pkgobjs:
                    if pobj["arch"] != "src":
                        pkgs.append(pobj["name"]) # + "." + pobj["arch"])
            log.error("Foe consumer id %s Packages to install %s" % (consumerid, pkgs))
            agent.packages.install(pkgs)
            consumer_pkg[consumerid] = pkgs
        return consumer_pkg
