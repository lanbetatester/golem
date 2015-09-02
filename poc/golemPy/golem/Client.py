import time
import datetime
import logging

from twisted.internet import task
from threading import Lock

from golem.network.p2p.P2PService import P2PService
from golem.network.p2p.Node import Node
from golem.task.TaskServer import TaskServer
from golem.task.TaskManager import TaskManagerEventListener

from golem.core.keys_auth import EllipticalKeysAuth

from golem.manager.NodeStateSnapshot import NodeStateSnapshot

from golem.AppConfig import AppConfig

from golem.Model import Database
from golem.network.transport.message import init_messages
from golem.ClientConfigDescriptor import ClientConfigDescriptor, ConfigApprover
from golem.environments.EnvironmentsManager import EnvironmentsManager
from golem.resource.ResourceServer import ResourceServer
from golem.resource.DirManager import DirManager
from golem.ranking.Ranking import Ranking, RankingDatabase

from golem.transactions.Ethereum.EthereumTransactionSystem import EthereumTransactionSystem

logger = logging.getLogger(__name__)

def emptyAddNodes(*args):
    pass

def startClient():
    init_messages()

    cfg = AppConfig.loadConfig()

    optNumPeers     = cfg.getOptimalPeerNum()
    managerAddress  = cfg.getManagerAddress()
    managerPort     = cfg.getManagerListenPort()
    startPort       = cfg.getStartPort()
    endPort         = cfg.getEndPort()
    seedHost        = cfg.getSeedHost()
    seedHostPort    = cfg.getSeedHostPort()
    sendPings       = cfg.getSendPings()
    pingsInterval   = cfg.getPingsInterval()
    clientUid       = cfg.getClientUid()
    addTasks        = cfg.getAddTasks()
    rootPath        = cfg.getRootPath()
    numCores        = cfg.getNumCores()
    maxResourceSize = cfg.getMaxResourceSize()
    maxMemorySize   = cfg.getMaxMemorySize()
    distResNum      = cfg.getDistributedResNum()
    appName         = cfg.getAppName()
    appVersion      = cfg.getAppVersion()
    pluginPort      = cfg.getPluginPort()

    gettingPeersInterval        = cfg.getGettingPeersInterval()
    gettingTasksInterval        = cfg.getGettingTasksInterval()
    taskRequestInterval         = cfg.getTaskRequestInterval()
    useWaitingForTaskTimeout    = cfg.getUseWaitingForTaskTimeout()
    waitingForTaskTimeout       = cfg.getWaitingForTaskTimeout()
    p2pSessionTimeout           = cfg.getP2pSessionTimeout()
    taskSessionTimeout          = cfg.getTaskSessionTimeout()
    resourceSessionTimeout      = cfg.getResourceSessionTimeout()

    estimatedPerformance        = cfg.getEstimatedPerformance()
    nodeSnapshotInterval        = cfg.getNodeSnapshotInterval()
    useDistributedResourceManagement = cfg.getUseDistributedResourceManagement()
    requestingTrust             = cfg.getRequestingTrust()
    computingTrust              = cfg.getComputingTrust()

    ethAccount                  = cfg.getEthAccount()
    useIp6                      = cfg.getUseIp6()

    configDesc = ClientConfigDescriptor()

    configDesc.clientUid        = clientUid
    configDesc.startPort        = startPort
    configDesc.endPort          = endPort
    configDesc.managerAddress   = managerAddress
    configDesc.managerPort      = managerPort
    configDesc.optNumPeers      = optNumPeers
    configDesc.sendPings        = sendPings
    configDesc.pingsInterval    = pingsInterval
    configDesc.addTasks         = addTasks
    configDesc.clientVersion    = 1
    configDesc.rootPath         = rootPath
    configDesc.numCores         = numCores
    configDesc.maxResourceSize  = maxResourceSize
    configDesc.maxMemorySize    = maxMemorySize
    configDesc.distResNum       = distResNum

    configDesc.seedHost               = seedHost
    configDesc.seedHostPort           = seedHostPort

    configDesc.appVersion             = appVersion
    configDesc.appName                = appName

    configDesc.pluginPort               = pluginPort
    configDesc.gettingPeersInterval     = gettingPeersInterval
    configDesc.gettingTasksInterval     = gettingTasksInterval
    configDesc.taskRequestInterval      = taskRequestInterval
    configDesc.useWaitingForTaskTimeout = useWaitingForTaskTimeout
    configDesc.waitingForTaskTimeout    = waitingForTaskTimeout
    configDesc.p2pSessionTimeout        = p2pSessionTimeout
    configDesc.taskSessionTimeout       = taskSessionTimeout
    configDesc.resourceSessionTimeout   = resourceSessionTimeout

    configDesc.estimatedPerformance     = estimatedPerformance
    configDesc.nodeSnapshotInterval     = nodeSnapshotInterval
    configDesc.maxResultsSendingDelay   = cfg.getMaxResultsSendingDelay()
    configDesc.useDistributedResourceManagement = useDistributedResourceManagement
    configDesc.requestingTrust          = requestingTrust
    configDesc.computingTrust           = computingTrust

    configDesc.ethAccount               = ethAccount
    configDesc.useIp6                   = useIp6


    logger.info("Adding tasks {}".format(addTasks))
    logger.info("Creating public client interface with uuid: {}".format(clientUid))
    c = Client(configDesc, config = cfg)

    logger.info("Starting all asynchronous services")
    c.startNetwork()

    return c

class GolemClientEventListener:
    ############################
    def __init__(self):
        pass

    ############################
    def taskUpdated(self, taskId):
        pass

    ############################
    def networkConnected(self):
        pass


class ClientTaskManagerEventListener(TaskManagerEventListener):
    #############################
    def __init__(self, client):
        self.client = client

    #######################
    def taskStatusUpdated(self, taskId):
        for l in self.client.listeners:
            l.taskUpdated(taskId)

    #######################
    def taskFinished(self, taskId):
        self.client.taskFinished(taskId)

class Client:

    ############################
    def __init__(self, configDesc, rootPath = "", config = ""):
        self.configDesc     = configDesc
        self.keysAuth       = EllipticalKeysAuth(configDesc.clientUid)
        self.configApprover = ConfigApprover(configDesc)

        #NETWORK
        self.node = Node(self.configDesc.clientUid, self.keysAuth.get_key_id())
        self.node.collectNetworkInfo(self.configDesc.seedHost, useIp6=self.configDesc.useIp6)
        logger.debug("Is super node? {}".format(self.node.isSuperNode()))
        self.p2service = None

        self.taskServer = None
        self.taskAdderServer = None
        self.lastNSSTime = time.time()

        self.lastNodeStateSnapshot = None

        self.nodesManagerClient = None

        self.doWorkTask = task.LoopingCall(self.__doWork)
        self.doWorkTask.start(0.1, False)

        self.listeners = []

        self.rootPath = rootPath
        self.cfg = config
        self.sendSnapshot = False
        self.snapshotLock = Lock()

        self.db = Database()
        self.db.checkNode(self.configDesc.clientUid)

        self.ranking = Ranking(self, RankingDatabase(self.db))

        self.transactionSystem = EthereumTransactionSystem(self.configDesc.clientUid, self.configDesc.ethAccount)

        self.environmentsManager = EnvironmentsManager()

        self.resourceServer = None
        self.resourcePort   = 0
        self.lastGetResourcePeersTime  = time.time()
        self.getResourcePeersInterval = 5.0

    ############################
    def startNetwork(self):
        logger.info("Starting network ...")

        logger.info("Starting p2p server ...")
        self.p2pservice = P2PService(self.node, self.configDesc, self.keysAuth, useIp6=self.configDesc.useIp6)
        time.sleep(1.0)

        logger.info("Starting resource server...")
        self.resourceServer = ResourceServer(self.configDesc, self.keysAuth, self, useIp6=self.configDesc.useIp6)
        self.resourceServer.startAccepting()
        time.sleep(1.0)
        self.p2pservice.setResourceServer(self.resourceServer)

        logger.info("Starting task server ...")
        self.taskServer = TaskServer(self.node, self.configDesc, self.keysAuth, self,
                                     useIp6=self.configDesc.useIp6)
        self.taskServer.startAccepting()

        self.p2pservice.setTaskServer(self.taskServer)

        time.sleep(0.5)
        self.taskServer.taskManager.registerListener(ClientTaskManagerEventListener(self))

    ############################
    def runAddTaskServer(self):
        from PluginServer import startTaskAdderServer
        from multiprocessing import Process, freeze_support
        freeze_support()
        self.taskAdderServer = Process(target = startTaskAdderServer, args=(self.getPluginPort(),))
        self.taskAdderServer.start()

    ############################
    def quit(self):
        if self.taskAdderServer:
            self.taskAdderServer.terminate()

    ############################
    def stopNetwork(self):
        #FIXME: Pewnie cos tu trzeba jeszcze dodac. Zamykanie serwera i wysylanie DisconnectPackege
        self.p2pservice         = None
        self.taskServer         = None
        self.nodesManagerClient = None

    ############################
    def enqueueNewTask(self, task):
        self.taskServer.taskManager.addNewTask(task)
        if self.configDesc.useDistributedResourceManagement:
            self.getResourcePeers()
            resFiles = self.resourceServer.addFilesToSend(task.taskResources, task.header.taskId, self.configDesc.distResNum)
            task.setResFiles(resFiles)

    ############################
    def getResourcePeers(self):
        self.p2pservice.sendGetResourcePeers()

    ############################
    def taskResourcesSend(self, taskId):
        self.taskServer.taskManager.resourcesSend(taskId)

    ############################
    def taskResourcesCollected(self, taskId):
        self.taskServer.taskComputer.taskResourceCollected(taskId)

    ############################
    def setResourcePort (self, resourcePort):
        self.resourcePort = resourcePort
        self.p2pservice.setResourcePeer(self.node.prvAddr, self.resourcePort)

    ############################
    def abortTask(self, taskId):
        self.taskServer.taskManager.abortTask(taskId)

    ############################
    def restartTask(self, taskId):
        self.taskServer.taskManager.restartTask(taskId)

    ############################
    def restartSubtask(self, subtaskId):
        self.taskServer.taskManager.restartSubtask(subtaskId)

    ############################
    def pauseTask(self, taskId):
        self.taskServer.taskManager.pauseTask(taskId)

    ############################
    def resumeTask(self, taskId):
        self.taskServer.taskManager.resumeTask(taskId)

    ############################
    def deleteTask(self, taskId):
        self.taskServer.removeTaskHeader(taskId)
        self.taskServer.taskManager.deleteTask(taskId)

    ############################
    def getId(self):
        return self.configDesc.clientUid

    ############################
    def getRootPath(self):
        return self.configDesc.rootPath

    ############################
    def increaseTrust(self, nodeId, stat, mod = 1.0):
        self.ranking.increaseTrust(nodeId, stat, mod)

    ############################
    def decreaseTrust(self, nodeId, stat, mod = 1.0):
        self.ranking.decreaseTrust(nodeId, stat, mod)

    ############################
    def getNeighboursDegree(self):
        return self.p2pservice.getPeersDegree()

    ############################
    def getSuggestedAddr(self, keyId):
        return self.p2pservice.suggestedAddrs.get(keyId)

    ############################
    def wantToStartTaskSession(self, keyId, nodeId, connId):
        self.p2pservice.wantToStartTaskSession(keyId, nodeId, connId)

    ############################
    def informAboutTaskNatHole(self, keyId, rvKeyId, addr, port, ansConnId):
        self.p2pservice.informAboutTaskNatHole(keyId, rvKeyId, addr, port, ansConnId)

    ############################
    def informAboutNatTraverseFailure(self, keyId, resKeyId, connId):
        self.p2pservice.informAboutNatTraverseFailure(keyId, resKeyId, connId)

    #TRANSACTION SYSTEM OPERATIONS
    ############################
    def acceptResult(self, taskId, subtaskId, priceMod, accountInfo):
        self.transactionSystem.addPaymentInfo(taskId, subtaskId, priceMod, accountInfo)

    ############################
    def taskRewardPaid(self, taskId, price):
        return self.transactionSystem.taskRewardPaid(taskId, price)

    ############################
    def taskRewardPaymentFailure(self, taskId, price):
        return self.transactionSystem.taskRewardPaymentFailure(taskId, price)

    ############################
    def globalPayForTask(self, taskId, payments):
        self.transactionSystem.globalPayForTask(taskId, payments)

    ############################
    def getReward(self, reward):
        self.transactionSystem.getReward(reward)

    ############################
    def getNewPaymentsTasks(self):
        return self.transactionSystem.getNewPaymentsTasks()

    #CLIENT CONFIGURATION
    ############################
    def registerListener(self, listener):
        assert isinstance(listener, GolemClientEventListener)
        self.listeners.append(listener)

    ############################
    def changeConfig(self, newConfigDesc):
        self.configDesc = self.configApprover.changeConfig(newConfigDesc)
        self.cfg.changeConfig(self.configDesc)
        self.resourceServer.changeResourceDir(self.configDesc)
        self.p2pservice.changeConfig(self.configDesc)
        self.taskServer.changeConfig(self.configDesc)

    ############################
    def registerNodesManagerClient(self, nodesManagerClient):
        self.nodesManagerClient = nodesManagerClient

    ############################
    def changeTimeouts(self, taskId, fullTaskTimeout, subtaskTimeout, minSubtaskTime):
        self.taskServer.changeTimeouts(taskId, fullTaskTimeout, subtaskTimeout, minSubtaskTime)

    ############################
    def unregisterListener(self, listener):
        assert isinstance(listener, GolemClientEventListener)
        for i in range(len(self.listeners)):
            if self.listeners[i] is listener:
                del self.listeners[ i]
                return
        logger.info("listener {} not registered".format(listener))

    ############################
    def querryTaskState(self, taskId):
        return self.taskServer.taskManager.querryTaskState(taskId)

    ############################
    def pullResources(self, taskId, listFiles):
        self.resourceServer.addFilesToGet(listFiles, taskId)
        self.getResourcePeers()

    ############################
    def addResourcePeer(self, clientId, addr, port, keyId, nodeInfo):
        self.resourceServer.addResourcePeer(clientId, addr, port, keyId, nodeInfo)

    ############################
    def supportedTask(self, thDictRepr):
        supported = self.__checkSupportedEnvironment(thDictRepr)
        return supported and self.__checkSupportedVersion(thDictRepr)

    ############################
    def getResDirs(self):
        dirs = { "computing": self.getComputedFilesDir(),
                 "received": self.getReceivedFilesDir(),
                 "distributed": self.getDistributedFilesDir()
                }
        return dirs

    def getComputedFilesDir(self):
        return self.taskServer.getTaskComputerRoot()

    def getReceivedFilesDir(self):
        return self.taskServer.taskManager.getTaskManagerRoot()

    def getDistributedFilesDir(self):
        return self.resourceServer.getDistributedResourceRoot()

    ############################
    def removeComputedFiles(self):
        dirManager = DirManager(self.configDesc.rootPath, self.configDesc.clientUid)
        dirManager.clearDir(self.getComputedFilesDir())

   ############################
    def removeDistributedFiles(self):
        dirManager = DirManager(self.configDesc.rootPath, self.configDesc.clientUid)
        dirManager.clearDir(self.getDistributedFilesDir())

   ############################
    def removeReceivedFiles(self):
        dirManager = DirManager(self.configDesc.rootPath, self.configDesc.clientUid)
        dirManager.clearDir(self.getReceivedFilesDir())

    ############################
    def getEnvironments(self):
        return self.environmentsManager.getEnvironments()

    ############################
    def changeAcceptTasksForEnvironment(self, envId, state):
        self.environmentsManager.changeAcceptTasks(envId, state)

    ############################
    def getComputingTrust(self, nodeId):
        return self.ranking.getComputingTrust(nodeId)

    ############################
    def sendGossip(self, gossip, sendTo):
        return self.p2pservice.sendGossip(gossip, sendTo)

    ############################
    def sendStopGossip(self):
        return self.p2pservice.sendStopGossip()

    ############################
    def getRequestingTrust(self, nodeId):
        return self.ranking.getRequestingTrust(nodeId)

    ############################
    def collectGossip(self):
        return self.p2pservice.popGossip()

    ############################
    def collectStoppedPeers(self):
        return self.p2pservice.popStopGossipFromPeers()

    ############################
    def collectNeighboursLocRanks(self):
        return self.p2pservice.popNeighboursLocRanks()

    ############################
    def pushLocalRank(self, nodeId, locRank):
        self.p2pservice.pushLocalRank(nodeId, locRank)

    ############################
    def getPluginPort(self):
        return self.configDesc.pluginPort

    ############################
    def getEthAccount(self):
        return self.configDesc.ethAccount

    ############################
    def taskFinished(self, taskId):
        self.transactionSystem.taskFinished(taskId)

    ############################
    def __tryChangeToNumber(self, oldValue, newValue, toInt = False, toFloat = False, name="Config"):
        try:
            if toInt:
                newValue = int(newValue)
            elif toFloat:
                newValue = float(newValue)
        except ValueError:
            logger.warning("{} value '{}' is not a number".format(name, newValue))
            newValue = oldValue
        return newValue

    ############################
    def __checkSupportedEnvironment(self, thDictRepr):
        env = thDictRepr.get("environment")
        if not env:
            return False
        if not self.environmentsManager.supported(env):
            return False
        return self.environmentsManager.acceptTasks(env)

    #############################
    def __checkSupportedVersion(self, thDictRepr):
        minV = thDictRepr.get("minVersion")
        if not minV:
            return True
        try:
            supported =  float(self.configDesc.appVersion) >= float(minV)
            return supported
        except ValueError:
            logger.error(
                "Wrong app version - app version {}, required version {}".format(
                    self.configDesc.appVersion,
                    minV
              )
          )
            return False

    ############################
    def __doWork(self):
        if self.p2pservice:
            if self.configDesc.sendPings:
                self.p2pservice.pingPeers(self.configDesc.pingsInterval)

            self.p2pservice.syncNetwork()
            self.taskServer.syncNetwork()
            self.resourceServer.syncNetwork()
            self.ranking.syncNetwork()


            if time.time() - self.lastNSSTime > self.configDesc.nodeSnapshotInterval:
                with self.snapshotLock:
                    self.__makeNodeStateSnapshot()
                self.lastNSSTime = time.time()
                for l in self.listeners:
                    l.checkNetworkState()

                #self.managerServer.sendStateMessage(self.lastNodeStateSnapshot)

    ############################
    def __makeNodeStateSnapshot(self, isRunning = True):

        peersNum            = len(self.p2pservice.peers)
        lastNetworkMessages = self.p2pservice.getLastMessages()

        if self.taskServer:
            tasksNum                = len(self.taskServer.taskKeeper.taskHeaders)
            remoteTasksProgresses   = self.taskServer.taskComputer.getProgresses()
            localTasksProgresses    = self.taskServer.taskManager.getProgresses()
            lastTaskMessages        = self.taskServer.getLastMessages()
            self.lastNodeStateSnapshot = NodeStateSnapshot(   isRunning
                                                           ,    self.configDesc.clientUid
                                                           ,    peersNum
                                                           ,    tasksNum
                                                           ,    self.p2pservice.node.pubAddr
                                                           ,    self.p2pservice.node.pubPort
                                                           ,    lastNetworkMessages
                                                           ,    lastTaskMessages
                                                           ,    remoteTasksProgresses  
                                                           ,    localTasksProgresses)
        else:
            self.lastNodeStateSnapshot = NodeStateSnapshot(self.configDesc.clientUid, peersNum)


        if self.nodesManagerClient:
            self.nodesManagerClient.sendClientStateSnapshot(self.lastNodeStateSnapshot)

    def getStatus(self):
        progress = self.taskServer.taskComputer.getProgresses()
        if len(progress) > 0:
            msg =  "Counting {} subtask(s):".format(len(progress))
            for k, v in progress.iteritems():
                msg = "{} \n {} ({}%)\n".format(msg, k, v.getProgress() * 100)
        else:
            msg = "Waiting for tasks...\n"

        peers = self.p2pservice.getPeers()

        msg += "Active peers in network: {}\n".format(len(peers))
        msg += "Budget: {}\n".format(self.transactionSystem.budget)
        return msg

    def getAboutInfo(self):
        return self.configDesc.appName, self.configDesc.appVersion
