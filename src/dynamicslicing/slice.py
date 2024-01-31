import libcst as cst
from dynapyt.analyses.BaseAnalysis import BaseAnalysis
from dynapyt.instrument.IIDs import IIDs
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union
from libcst.metadata import (
    PositionProvider,
)
import os

class Slice(BaseAnalysis):
    def __init__(self, source_path):
        with open(source_path, "r") as file:
            source = file.read()
        self.iid_object = IIDs(source_path)
        self.source_path = source_path
        self.code = source
        self.comment_line=0 #: int # the line number of the slice criterion
        self.keep_lines=[] # the lines of Class and call of slice_me()
        self.asts = {}
        self.graph={}
        self.control_graph={}   
        self.slice_results_line=set() # the lines of slice results
             
    def get_location_name(self,dyn_ast,iid):
        '''
        Retrieves the location and name information for a given dynamic ast node and id.
        Returns:
        - Tuple: the node, its type, and its code line.
        '''
        from dynapyt.utils.nodeLocator import get_node_by_location
        location = self.iid_to_location(dyn_ast,iid)
        node = get_node_by_location(self._get_ast(dyn_ast)[0], location)
        codeline=location.start_line
        return node, type(node),codeline
        
    def get_line_infomation(self): 
        '''
        Get the line numbers of:
        - 1.comment_line: the number of the line code that are used as slice criterion. 
        - 2.keep_lines: the number of lines of code for used Class and the call code of slice_me() by traversing the location.
        '''
        ### 1. get the line number of the comment line of slice criterion
        def get_comment():
            class GetComment(cst.CSTTransformer):
                METADATA_DEPENDENCIES = ( PositionProvider,)
                def __init__(self):
                    self.cl=0
                def on_leave(self, original_node:"CSTNode", updated_node: "CSTNode" ) :#-> Union["CSTNode", RemovalSentinel]:
                    location = self.get_metadata(PositionProvider, original_node)
                    if isinstance(updated_node,cst.Comment):
                        self.cl=location.start.line
                    return updated_node
            syntax_tree = cst.parse_module(self.code)
            wrapper = cst.metadata.MetadataWrapper(syntax_tree)
            temp = GetComment()
            _ = wrapper.visit(temp)
            return temp.cl
        self.comment_line=get_comment()

        ### 2.get the lines of Class and call of slice_me()
        syntax_tree = cst.parse_module(self.code)
        wrapper = cst.metadata.MetadataWrapper(syntax_tree)
        thepos = wrapper.resolve(PositionProvider)
        otherpart_index=[]
        index1=None
        code_body=wrapper.module.body

        for i in range(len(code_body)):  #many parts, such as ClassDef, FunctionDef, SimpleStatementLine
            try:
                if code_body[i].name.value == 'slice_me':
                    index1=i
                else:
                    otherpart_index.append(i)  #save ClassDef, SimpleStatementLine
            except Exception as e:
                otherpart_index.append(i)  #save ClassDef, SimpleStatementLine
        node=wrapper.module.body[index1].body.body # get the node of def slice_me()
        
        for i in otherpart_index:
            nodes=wrapper.module.body[i]
            self.keep_lines.append([thepos[nodes].start.line,thepos[nodes].end.line])

    def begin_execution(self) -> None:
        '''
        Initiates the execution of the analysis.
        '''
        self.get_line_infomation()
        print('keep_lines',self.keep_lines)
        print('comment_line',self.comment_line) 

    def read(self, dyn_ast: str, iid: int, val: Any) -> Any:
        a,b,c =self.get_location_name(dyn_ast,iid) 
        # print('read')
        # print(c,b) #for debug
        if c not in self.graph:
            self.graph[c] =  {'write':set(),'read':set(),'addtion':set()}
        if 'libcst._nodes.expression.Name' in str(b):
            self.graph[c]['read'].add(a.value)
        elif 'libcst._nodes.expression.Attribute' in str(b):
            if a.attr.value in ['append','pop','remove', 'insert','extend']: 
                self.graph[c]['write'].add(a.value.value) # modify the code, so here should be 'write'
            else:
                self.graph[c]['read'].add(a.value.value)
        else:
            pass

    def write(
        self, dyn_ast: str, iid: int, old_vals: List[Callable], new_val: Any
    ) -> Any:
        a,b,c=self.get_location_name(dyn_ast,iid) #a,b,c are node, type_node, codeline
        # print('write')
        # print(c,b)

        if c not in self.graph:
            self.graph[c] =  {'write':set(),'read':set(),'addtion':set()}
        if 'libcst._nodes.statement.Assign' in str(b):
            if type(a.targets[0].target.value) is str:
                self.graph[c]['write'].add(a.targets[0].target.value)
            else:
                self.graph[c]['write'].add(a.targets[0].target.value.value)
            if 'libcst._nodes.expression.Subscript' in  str(type(a.targets[0].target)):
                self.graph[c]['read'].add(a.targets[0].target.value.value) # in test_5, like ages[-1]=150, here should be 'read'
        elif 'libcst._nodes.statement.AugAssign' in str(b):
            if 'libcst._nodes.expression.Subscript' in str(type(a.target)) or 'libcst._nodes.expression.Attribute' in str(type(a.target)):
                self.graph[c]['write'].add(a.target.value.value)
            else:
                self.graph[c]['write'].add(a.target.value)
        else:
            pass

        # For addition test
        from pathlib import Path
        path=Path(self.source_path)
        func_name=str(path.parent.name)+'.'
        # if exist the code like 'p2 = p1', the judgment condition is p1. p1 is a object or list： 
        if func_name in str(type(new_val)) or 'list' in str(type(new_val)): 
            try:
                if isinstance(a.value.value,str):   #if the node exist a.value.value, and it is a str
                    self.graph[c]['addtion'].add(a.value.value) 
            except Exception as e:
                pass

    def enter_control_flow(
        self, dyn_ast: str, iid: int, cond_value: bool
    ) -> Optional[bool]:
        a,b,c =self.get_location_name(dyn_ast,iid) 
        # print('enter_control_flow')
        # print(c,b) #for debug 

        ### 1. initialize the control_graph
        body_line=[self.iid_object.iid_to_location[iid].start_line+1, self.iid_object.iid_to_location[iid].end_line+1]
        body_line_list=[i for i in range(body_line[0],body_line[1])]
        if c not in self.control_graph:
            self.control_graph[c] =  {'read':set(),'body_lines':set()}
        for i in body_line_list:
            self.control_graph[c]['body_lines'].add(i)
        
        ### 2.1 For
        if 'libcst._nodes.statement.For' in str(type(a)):
            strr=a.iter.value
        else:
            ### 2.2 IF
            if 'libcst._nodes.expression.Attribute' in str(type(a.test.left)):
                strr=a.test.left.value.value
                self.control_graph[c]['read'].add(strr)
                try:  
                    strr_right=a.test.comparisons[0].comparator.value
                    self.control_graph[c]['read'].add(strr_right)
                except Exception as e:
                    pass
            
            ### 2.3 while
            elif 'libcst._nodes.expression.BooleanOperation' in str(type(a.test.left)) and 'libcst._nodes.statement.While' in str(type(a)): 
                strr1=a.test.left.left.left.value.value  
                self.control_graph[c]['read'].add(strr1)
                try:
                    strr1_right=a.test.left.left.comparisons[0].comparator.value
                    self.control_graph[c]['read'].add(strr1_right)
                except Exception as e:
                    pass
                strr2=a.test.left.right.left.value.value  
                self.control_graph[c]['read'].add(strr2)
                try:
                    strr2_right=a.test.right.right.comparisons[0].comparator.value
                    self.control_graph[c]['read'].add(strr2_right)
                except Exception as e:
                    pass
            else:
                strr=a.test.left.value
                self.control_graph[c]['read'].add(strr)

            try:
                strr_right=a.body.body[0].body[0].target.value.value
                self.control_graph[c]['read'].add(strr_right)
            except Exception as e:
                pass

    def pre_call(
        self, dyn_ast: str, iid: int, function: Callable, pos_args: Tuple, kw_args: Dict
    ):
        '''
        hook for 'Person.increase_age' in test cases
        '''
        if 'Person.increase_age' in str(function):
            a,b,c=self.get_location_name(dyn_ast,iid)
            # print('pre_call')
            # print(c,b) #for debug
            if c not in self.graph:
                self.graph[c] =  {'write':set(),'read':set(),'addtion':set()}
            self.graph[c]['write'].add(a.func.value.value)


    def print_graph(self,graphname='graph'):
        '''
        Prints the content of the graph attribute for debugging purposes.
        '''
        if graphname=='graph':
            print('graph:')
            for i,j in self.graph.items():
                print(i,j)
        else:
            print('control_graph:')
            for i,j in self.control_graph.items():
                print(i,j)

    def slicepoint(self,graph_line,slice_point):
        '''
        After getting the graph. Use recursion to get slice nodes.
        '''
        self.slice_results_line.add(graph_line[0])
        for j in slice_point:
            for k in range(1,len(graph_line)):
                if j in self.graph[graph_line[k]]['write']:
                    self.slicepoint(graph_line[k:],self.graph[graph_line[k]]['read'])         

    def end_execution(self) -> None:
        '''
        # Finalizes the execution of the analysis.
        # 1.Based on the graph, control graph and keep_lines, find the lines to be sliced through recursion.
        # 2.Removes unnecessary lines based on the lines_to_keep and writes the modified code to a new file
        # 3.Write the new code to slice.py
        '''
        print('-------------------------')
        self.print_graph('control_graph')
        self.print_graph()

        ### 1.Based on the graph, control graph and keep_lines, find the lines to be sliced through recursion.
        # 1.1.Recursion for the graph(from hook read and write, (and pre_call)):
        graph_line=[i for i in reversed(self.graph.keys())]
        begin_slice_line=graph_line.index(self.comment_line)   
        graph_line=graph_line[begin_slice_line:] 
        slice_point=self.graph[graph_line[0]]['read']
        self.slicepoint(graph_line[0:],slice_point)

        # 1.2.Recursion for addtion test(milestone2 test 11, 12):
        for i in self.graph:
            if self.graph[i]['addtion'] != set():
                templist= [x for x in self.slice_results_line if x < i]
                if templist != []:
                    for j in range(len(graph_line)):
                        if self.graph[graph_line[j]]['write']==self.graph[i]['write']:
                            self.slicepoint(graph_line[j:],self.graph[graph_line[j]]['read'])
        
        print('\n self.slice_results_line before control graph',self.slice_results_line)

        # 1.3.Recursion for the graph of control flow(from hook enter_control_flow):
        control_line=[i for i in reversed(self.control_graph.keys())]
        for i in control_line:
            graph_line=[i for i in reversed(self.graph.keys())]
            for j in self.control_graph[i]['body_lines']:
                if j in self.slice_results_line:
                    self.slice_results_line.add(i)
                    if self.control_graph[i]['read'] != set():
                        begin_slice_line=graph_line.index(i)   
                        graph_line=graph_line[begin_slice_line:]
                        read_point=self.control_graph[i]['read']
                        self.slicepoint(graph_line[0:],read_point)

        # 1.4.get the lines of keep_lines (Class(from the start line to the end line) and call of slice_me())
        for i in self.keep_lines: 
            for j in range(i[0],i[1]+1):
                self.slice_results_line.add(j)
        lines_to_keep=[str(i) for i in self.slice_results_line]
        print('self.slice_results_line final',self.slice_results_line)

        ### 2.Removes unnecessary lines based on the lines_to_keep and writes the modified code to a new file:
        def remove_lines(code: str, lines_to_keep : List[int]) -> str:
            class RemoveLines(cst.CSTTransformer):
                METADATA_DEPENDENCIES = ( PositionProvider,)
                def __init__(self, lines_to_keep, control_graph):
                    self.lines_to_keep = lines_to_keep
                    self.control_graph_cst=control_graph
                    self.cl=0

                def on_leave(self, original_node:"CSTNode", updated_node: "CSTNode" ) :#-> Union["CSTNode", RemovalSentinel]:
                    location = self.get_metadata(PositionProvider, original_node)

                    ### 2.1. remove simplestatementline
                    if isinstance(updated_node, cst.SimpleStatementLine) and str(location.start.line) not in self.lines_to_keep:
                        return cst.RemoveFromParent()
                    elif isinstance(updated_node,cst.EmptyLine):
                        return cst.RemoveFromParent()
                    else:
                        ### 2.2. remove control flow
                        namelist=['libcst._nodes.statement.If','libcst._nodes.statement.For','libcst._nodes.statement.While']
                        for i in namelist:
                            if i in str(type(updated_node)) and str(location.start.line) not in self.lines_to_keep:
                                return cst.RemoveFromParent()
                        else:
                            ### 2.3. remove elif or else
                            if ('If' in str(type(updated_node)) or 'Else' in str(type(updated_node))) and location.start.line not in self.control_graph_cst:  
                                flag=1
                                for i in self.control_graph_cst:
                                    if location.start.line > i and location.start.line in self.control_graph_cst[i]['body_lines'] :
                                        flag=0
                                        for j in self.control_graph_cst[i]['body_lines']:
                                            if j > location.start.line and str(j) in self.lines_to_keep:
                                                flag=1
                                if flag==0:
                                    return cst.RemoveFromParent()
                                else:
                                    return updated_node
                            else:     
                                return updated_node

            syntax_tree = cst.parse_module(code)
            wrapper = cst.metadata.MetadataWrapper(syntax_tree)
            code_modifier = RemoveLines(lines_to_keep,self.control_graph)
            new_syntax_tree = wrapper.visit(code_modifier)
            return new_syntax_tree.code

        ### 3.Write the new code to slice.py
        def write_to_file(code: str) -> str:
            with open(os.path.dirname(self.source_path)+'/sliced.py','w') as f:
                f.write(code)
    
        code=remove_lines(self.code,lines_to_keep)
        print('\n',code)
        write_to_file(code)

    