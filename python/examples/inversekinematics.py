#!/usr/bin/env python
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import with_statement # for python 2.5
__author__ = 'Rosen Diankov'
__copyright__ = 'Copyright (C) 2009-2010 Rosen Diankov (rosen.diankov@gmail.com)'
__license__ = 'Apache License, Version 2.0'

from openravepy import *
from openravepy.interfaces import BaseManipulation
from openravepy.ikfast import IKFastSolver
from numpy import *
import time,platform
import distutils
from distutils import ccompiler
from optparse import OptionParser

class InverseKinematicsModel(OpenRAVEModel):
    """Generates analytical inverse-kinematics solutions, compiles them into a shared object/DLL, and sets the robot's iksolver"""
    Type_6D=0
    Type_Rotation3D=1
    Type_Direction3D=2
    Type_Translation3D=3
    def __init__(self,robot,type=Type_6D):
        OpenRAVEModel.__init__(self,robot=robot)
        self.type = type
        if self.type == self.Type_Rotation3D:
            self.dofexpected = 3
        elif self.type == self.Type_Direction3D:
            self.dofexpected = 2
        elif self.type == self.Type_Translation3D:
            self.dofexpected = 3
        elif self.type == type == self.Type_6D:
            self.dofexpected = 6
        else:
            raise ValueError('bad type')
        self.iksolver = None
    
    def has(self):
        return self.iksolver is not None and self.manip.HasIKSolver()
    
    def load(self):
        self.iksolver = None
        if self.manip.HasIKSolver():
            self.iksolver = self.env.CreateIkSolver(self.manip.GetIKSolverName()) if self.manip.HasIKSolver() else None
        if self.iksolver is None:
            with self.env:
                ikfastproblem = [p for p in self.env.GetLoadedProblems() if p.GetXMLId() == 'IKFast'][0]
                ikname = 'ikfast.%s.%s'%(self.robot.GetRobotStructureHash(),self.manip.GetName())
                if ikfastproblem.SendCommand('AddIkLibrary %s %s'%(ikname,self.getfilename())) is None:
                    return False
                self.iksolver = self.env.CreateIkSolver(ikname)
                if self.iksolver is not None:
                    self.manip.SetIKSolver(self.iksolver)
                    if not self.manip.InitIKSolver():
                        return False
        return self.has()
    
    def save(self):
        pass # already saved as a lib
    
    def getfilename(self):
        basename = 'ikfast.' + self.manip.GetName()
        if self.type == self.Type_Rotation3D:
            sourcefilename += 'r3d'
        elif self.type == self.Type_Direction3D:
            sourcefilename += 'd2d'
        elif self.type == self.Type_Translation3D:
            basename += 't3d'
        elif self.type == self.Type_6D:
            basename += '6d'
        else:
            raise ValueError('bad type')
        return ccompiler.new_compiler().shared_object_filename(basename=basename,output_dir=OpenRAVEModel.getfilename(self))
    
    def generateFromOptions(self,options):
        type = self.Type_6D
        if options.rotation3donly:
            type = self.Type_Rotation3D
        if options.rotation2donly:
            type = self.Type_Direction3D
        if options.translation3donly:
            type = self.Type_Translation3D
        self.generate(freejoints=options.freejoints,usedummyjoints=options.usedummyjoints,type=type,accuracy=options.accuracy,precision=options.precision,force=options.force)
    
    def generate(self,freejoints=None,usedummyjoints=False,type=None,accuracy=None,precision=None,force=False):
        if type is not None:
            self.type = type
        output_filename = self.getfilename()
        sourcefilename = os.path.splitext(output_filename)[0]
        if self.type == self.Type_Rotation3D:
            solvefn=IKFastSolver.solveFullIK_Rotation3D
        elif self.type == self.Type_Direction3D:
            solvefn=IKFastSolver.solveFullIK_Direction3D
        elif self.type == self.Type_Translation3D:
            solvefn=IKFastSolver.solveFullIK_Translation3D
        elif self.type == self.Type_6D:
            solvefn=IKFastSolver.solveFullIK_6D

        solvejoints = list(self.manip.GetArmJoints())
        if freejoints is not None:
            for jointname in freejoints:
                solvejoints.remove(jointname)
        else:
            freejoints = []

        if len(solvejoints) > self.dofexpected:
            print 'choosing free joints'
            freejoints = []
            for i in range(len(solvejoints) - self.dofexpected):
                if self.dofexpected == 6:
                    freejoints.append(solvejoints.pop(2))
                else:
                    freejoints.append(solvejoints.pop(0))

        if not len(solvejoints) == self.dofexpected:
            raise ValueError('Need %d solve joints, got: %d'%(self.dofexpected, len(solvejoints)))

        sourcefilename += '_' + '_'.join(str(ind) for ind in solvejoints)
        if len(freejoints)>0:
            sourcefilename += '_f'+'_'.join(str(ind) for ind in freejoints)
        sourcefilename += '.cpp'
        if force or not os.path.isfile(sourcefilename):
            print 'generating inverse kinematics file %s'%sourcefilename
            mkdir_recursive(OpenRAVEModel.getfilename(self))
            solver = IKFastSolver(kinbody=self.robot,accuracy=accuracy,precision=precision)
            code = solver.generateIkSolver(self.manip.GetBase().GetIndex(),self.manip.GetEndEffector().GetIndex(),solvejoints=solvejoints,freeparams=freejoints,usedummyjoints=usedummyjoints,solvefn=solvefn)
            if len(code) == 0:
                raise ValueError('failed to generate ik solver for robot %s:%s'%(self.robot.GetName(),self.manip.GetName()))
            open(sourcefilename,'w').write(code)

        # compile the code and create the shared object
        compiler,compile_flags = self.getcompiler()
        try:
           output_dir = os.path.relpath('/',os.getcwd())
        except AttributeError: # python 2.5 does not have os.path.relpath
           output_dir = self.myrelpath('/',os.getcwd())
        objectfiles = compiler.compile(sources=[sourcefilename],macros=[('IKFAST_CLIBRARY',1)],extra_postargs=compile_flags,output_dir=output_dir)
        compiler.link_shared_object(objectfiles,output_filename=output_filename)
        if not self.load():
            return ValueError('failed to generate ik solver')
    def autogenerate(self,forcegenerate=True):
        if self.robot.GetRobotStructureHash() == '409764e862c254605cafb9de013eb531' and self.manip.GetName() == 'arm' and self.type == self.Type_6D:
            self.generate(freejoints=[self.robot.GetJoint('Shoulder_Roll').GetJointIndex()])
        else:
            if not forcegenerate:
                raise ValueError('failed to find auto-generation parameters')
            self.generate()
    
    @staticmethod
    def getcompiler():
        compiler = ccompiler.new_compiler()
        compile_flags = []
        if compiler.compiler_type == 'msvc':
            compile_flags.append('/Ox')
            try:
                # make sure it is correct version!
                cname,cver = openravepyCompilerVersion().split()
                if cname == 'msvc':
                    majorVersion = int(cver)/100-6
                    minorVersion = mod(int(cver),100)/10.0
                    if abs(compiler._MSVCCompiler__version - majorVersion+minorVersion) > 0.001:
                        # not the same version, look for a different compiler
                        distutils.msvc9compiler.VERSION = majorVersion + minorVersion
                        newcompiler = ccompiler.new_compiler()
                        if newcompiler is not None:
                            compiler = newcompiler
            except:
                pass
        else:
            compiler.add_library('stdc++')
            if compiler.compiler_type == 'unix':
                compile_flags.append('-O3')
                compile_flags.append('-fPIC')
        return compiler,compile_flags
    @staticmethod
    def myrelpath(path, start=os.path.curdir):
        """Return a relative version of a path"""
        if not path:
            raise ValueError("no path specified")

        start_list = os.path.abspath(start).split(os.path.sep)
        path_list = os.path.abspath(path).split(os.path.sep)

        # Work out how much of the filepath is shared by start and path.
        i = len(os.path.commonprefix([start_list, path_list]))

        rel_list = [os.path.pardir] * (len(start_list)-i) + path_list[i:]
        if not rel_list:
            return os.path.curdir
        return os.path.join(*rel_list)

    @staticmethod
    def CreateOptionParser():
        parser = OpenRAVEModel.CreateOptionParser()
        parser.description='Computes the closed-form inverse kinematics equations of a robot manipulator, generates a C++ file, and compiles this file into a shared object which can then be loaded by OpenRAVE'
        parser.add_option('--freejoint', action='append', type='int', dest='freejoints',default=[],
                          help='Optional joint index specifying a free parameter of the manipulator. If not specified, assumes all joints not solving for are free parameters. Can be specified multiple times for multiple free parameters.')
        parser.add_option('--precision', action='store', type='int', dest='precision',default=10,
                          help='The precision to compute the inverse kinematics in, default is 10 decimal digits.')
        parser.add_option('--accuracy', action='store', type='float', dest='accuracy',default=1e-7,
                          help='The small number that will be recognized as a zero used to eliminate floating point errors (default is 1e-7).')
        parser.add_option('--force', action='store_true', dest='force',default=False,
                          help='If true, will always rebuild the ikfast c++ file, regardless of its existence.')
        parser.add_option('--rotation3donly', action='store_true', dest='rotation3donly',default=False,
                          help='If true, need to specify only 3 solve joints and will solve for a target rotation')
        parser.add_option('--rotation2donly', action='store_true', dest='rotation2donly',default=False,
                          help='If true, need to specify only 2 solve joints and will solve for a target direction')
        parser.add_option('--translation3donly', action='store_true', dest='translation3donly',default=False,
                          help='If true, need to specify only 3 solve joints and will solve for a target translation')
        parser.add_option('--usedummyjoints', action='store_true',dest='usedummyjoints',default=False,
                          help='Treat the unspecified joints in the kinematic chain as dummy and set them to 0. If not specified, treats all unspecified joints as free parameters.')
        parser.add_option('--numiktests', action='store',type='int',dest='numiktests',default=None,
                          help='Will test the ik solver against NUMIKTESTS random robot configurations and program will exit with 0 if success rate exceeds the test success rate, otherwise 1.')
        return parser
    @staticmethod
    def RunFromParser(Model=None,parser=None):
        if parser is None:
            parser = InverseKinematicsModel.CreateOptionParser()
        (options, args) = parser.parse_args()
        Model = lambda robot: InverseKinematicsModel(robot=robot)
        OpenRAVEModel.RunFromParser(Model=Model,parser=parser)

        if options.numiktests is not None:
            print 'testing the success rate of robot ',options.robot
            env = Environment()
            try:
                robot = env.ReadRobotXMLFile(options.robot)
                env.AddRobot(robot)
                basemanip = BaseManipulation(robot)
                successrate = basemanip.DebugIK(numiters=options.numiktests)
                print 'success rate is: ',successrate
            finally:
                env.Destroy()

if __name__ == "__main__":
     InverseKinematicsModel.RunFromParser()
