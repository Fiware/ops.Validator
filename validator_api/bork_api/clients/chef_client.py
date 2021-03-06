# -*- coding: utf-8 -*-

#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import os
import re

from oslo_config import cfg
from oslo_log import log as logging
from bork_api.clients.docker_client import DockerManager

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


def check_chef_cookbook(cb_path):
    """
    Test if a directory contains a cookbook
    :param cb_path: directory name
    :return: test result
    """
    LOG.info("checking %s" % cb_path)
    check = False
    # check if the item is a directory
    if os.path.isdir(cb_path):
        # check if the item has a recipes directory
        if os.path.isdir(os.path.join(cb_path, "recipes")):
            check = True
            LOG.debug("Cookbook found: %s" % cb_path)
            if not os.path.exists(os.path.join(cb_path, "Berksfile")):
                generate_berksfile(cb_path)
    if not check:
        LOG.debug("Not a cookbook: %s" % cb_path)
    return check


def generate_berksfile(cb_path):
    """
    Generates a dependencies file if none are detected
    :param cb_path:
    :return:
    """
    status = False
    try:
        bf_conts = 'source "https://supermarket.chef.io"\n\nmetadata\n'
        mf = os.path.join(cb_path, "metadata.rb")
        bf = os.path.join(cb_path, "Berksfile")
        if os.path.exists(mf):
            with open(mf) as f:
                for dep in re.findall(r"depends\s['\"]([^['\"]]+?)['\"]", f.read()):
                    bf_conts += 'cookbook "%s"' % dep
        LOG.info("Berksfile not detected. Generating in %s" % bf)
        with open(bf, "w") as f:
            f.write(bf_conts)
        status = True
    except:
        pass
    return status


def check_chef_recipe(rec):
    """
    Checks if the given file is a chef recipe
    :param rec: file path
    :return: check result
    """
    return rec.lower().endswith(".rb")


def list_recipes(cb_path):
    """
    :return: list of all recipes in the current cookbook
    """
    valid = []
    for rec in os.listdir(os.path.join(cb_path, "recipes")):
        if check_chef_recipe(rec):
            valid.append(rec)
    return valid


class ChefClient(object):
    """
    Wrapper for Docker client
    """

    def __init__(self):
        self.dc = DockerManager()

    def run_install(self, user, cookbook, image):
        """Run download and install command
        :param cookbook: cookbook to process
        :return msg: operation result
        """
        # try:
        contname = self.dc.generate_container_name(user, cookbook, image)
        cbpath = os.path.join(CONF.clients_git.repo_path, self.dc.generate_user_name(user))
        # set chef default cookbook path
        cmd_path = "echo \"cookbook_path ['{}']\nlog_level :debug \"> /etc/chef/client.rb".format(cbpath)
        LOG.debug("Chef path: %s" % cmd_path)
        self.dc.execute_command(contname, cmd_path)
        # set knife default cookbook path
        cmd_path = "echo \"cookbook_path ['{}']\nlog_level :debug \"> /etc/chef/knife.rb".format(cbpath)
        LOG.debug("Knife path: %s" % cmd_path)
        self.dc.execute_command(contname, cmd_path)
        # run install command
        currentpath = os.path.join(cbpath, cookbook)
        cmd_install = CONF.clients_chef.cmd_install.format(currentpath, cbpath)
        LOG.debug("Install command: %s" % cmd_install)
        resp_install = self.dc.execute_command(contname, cmd_install)
        msg = {
            'success': True,
            'response': resp_install
        }
        for line in resp_install.splitlines():
            if "ERROR" in line:
                msg['success'] = False
        LOG.debug("Install result: %s" % resp_install)
        # except Exception as e:
        #     LOG.error(_LW("Chef install exception: %s" % e))
        #     raise CookbookInstallException(cookbook=cookbook)
        return msg

    def run_test(self, user, cookbook, image):
        """ Test cookbook syntax
        :param cookbook: cookbook to test
        :return msg: dictionary with results and state
        """
        # try:
        contname = self.dc.generate_container_name(user, cookbook, image)
        cmd_syntax = CONF.clients_chef.cmd_syntax.format(cookbook)
        LOG.debug("Syntax cmd: %s" % cmd_syntax)
        resp_test = self.dc.execute_command(contname, cmd_syntax)
        msg = {
            'success': True,
            'response': resp_test
        }
        for line in resp_test.splitlines():
            if "ERROR" in line:
                msg['success'] = False
        LOG.debug("Test result: %s" % resp_test)
        # except Exception as e:
        #     self.dc.remove_container(contname)
        #     LOG.error(_LW("Cookbook syntax exception %s" % e))
        #     raise CookbookSyntaxException(cookbook=cookbook)
        return msg

    def run_deploy(self, user, cookbook, recipe, image):
        """ Run cookbook deployment
        :param cookbook: cookbook to deploy
        :return msg: dictionary with results and state
        """
        # try:
        # launch execution
        contname = self.dc.generate_container_name(user, cookbook, image)
        # # run deploy
        cmd_deploy = CONF.clients_chef.cmd_deploy.format(cookbook, recipe.replace(".rb", ""))
        resp_launch = self.dc.execute_command(contname, cmd_deploy)
        msg = {
            'success': True,
            'response': resp_launch
        }
        LOG.debug("Launch result: %s" % resp_launch)
        if resp_launch is None or "FATAL" in resp_launch:
            msg['success'] = False
        # except Exception as e:
        #     self.dc.remove_container(self.container)
        #     LOG.error(_LW("Cookbook deployment exception %s" % e))
        #     raise CookbookDeploymentException(cookbook=cookbook)
        return msg

    def cookbook_deployment_test(self, user, cookbook, recipe='default', image='default'):
        """
        Try to process a cookbook and return results
        :param cookbook: cookbook to deploy
        :param recipe: recipe to deploy
        :param image: image to deploy to
        :return: dictionary with results
        """
        LOG.debug("Sending cookbook to docker server at %s" % self.dc._url)
        b_success = True
        msg = {}
        self.dc.run_container(user, cookbook, image)
        # inject custom solo.json/solo.rb file
        json_cont = CONF.clients_chef.cmd_config % (cookbook, recipe)
        cmd_inject = CONF.clients_chef.cmd_inject.format(json_cont)
        self.dc.execute_command(self.dc.generate_container_name(user, cookbook, image), cmd_inject)

        msg['install'] = self.run_install(user, cookbook, image)
        b_success &= msg['install']['success']
        msg['test'] = self.run_test(user, cookbook, image)
        b_success &= msg['test']['success']
        msg['deploy'] = self.run_deploy(user, cookbook, image)
        b_success &= msg['deploy']['success']

        # check execution output
        if b_success:
            msg['result'] = {
                'success': True,
                'result': "Cookbook %s successfully deployed\n" % cookbook
            }
        else:
            msg['result'] = {
                'success': False,
                'result': "Error deploying cookbook {}\n".format(cookbook)
            }
            LOG.error(msg)
        self.dc.remove_container(image)
        return msg
