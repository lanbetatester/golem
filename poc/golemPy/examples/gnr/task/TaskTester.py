import os
from threading import Thread, Lock
import shutil

from golem.task.TaskBase import Task
from golem.task.resource.Resource import TaskResourceHeader, decompressDir
from golem.task.TaskComputer import PyTaskThread


class TaskTester:
    #########################
    def __init__( self, task, finishedCallback ):
        assert isinstance( task, Task )
        self.task               = task
        self.testTaskResPath    = None
        self.tmpDir             = None
        self.success            = False
        self.lock               = Lock()
        self.tt                 = None
        self.finishedCallback   = finishedCallback

    #########################
    def run( self ):
        try:
            success = self.__prepareResources()
            self.__prepareTmpDir()

            if not success:
                return False

            ctd = self.task.queryExtraDataForTestTask()


            self.tt = PyTaskThread(  self,
                                ctd.subtaskId,
                                ctd.workingDirectory,
                                ctd.srcCode,
                                ctd.extraData,
                                ctd.shortDescription,
                                self.testTaskResPath,
                                self.tmpDir )
            self.tt.start()

        except Exception as exc:
            print "Task not tested properly: {}".format( exc )
            self.finishedCallback( False )

    #########################
    def getProgress( self ):
        if self.tt:
            with self.lock:
                if self.tt.getError():
                    print "Task not tested properly"
                    self.finishedCallback( False )
                    return 0
                return self.tt.getProgress()
        return None

    #########################
    def __prepareResources( self ):

        self.testTaskResPath = "testing_task_resources"
        self.testTaskResPath = os.path.abspath( self.testTaskResPath )
        if not os.path.exists( self.testTaskResPath ):
            os.makedirs( self.testTaskResPath )
        else:
            shutil.rmtree( self.testTaskResPath, True )
            os.makedirs( self.testTaskResPath )

        rh = TaskResourceHeader( "testing_task_resources" )
        resFile = self.task.prepareResourceDelta( self.task.header.taskId, rh )

        if resFile:
            decompressDir( self.testTaskResPath, resFile )

        return True
    #########################
    def __prepareTmpDir( self ):
        self.tmpDir = "testing_task_tmp"
        self.tmpDir = os.path.abspath( self.tmpDir )
        if not os.path.exists( self.tmpDir ):
            os.makedirs( self.tmpDir )
        else:
            shutil.rmtree( self.tmpDir, True )
            os.makedirs( self.tmpDir )

    ###########################
    def taskComputed( self, taskThread ):
        if taskThread.result:
            print "Test task computation success !"
            self.finishedCallback( True )
        else:
            print "Test task computation failed !!!"
            self.finishedCallback( False )