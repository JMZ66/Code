import gurobipy as gp
from gurobipy import GRB

# 初始化数独问题 (0 表示未填的格子)
board = [
    [5, 3, 0, 0, 7, 0, 0, 0, 0],
    [6, 0, 0, 1, 9, 5, 0, 0, 0],
    [0, 9, 8, 0, 0, 0, 0, 6, 0],
    [8, 0, 0, 0, 6, 0, 0, 0, 3],
    [4, 0, 0, 8, 0, 3, 0, 0, 1],
    [7, 0, 0, 0, 2, 0, 0, 0, 6],
    [0, 6, 0, 0, 0, 0, 2, 8, 0],
    [0, 0, 0, 4, 1, 9, 0, 0, 5],
    [0, 0, 0, 0, 8, 0, 0, 7, 9]
]

# 创建一个新的模型
model = gp.Model("sudoku")

# 创建决策变量 x[i,j,k]，表示在格子 (i,j) 填入数字 k+1
x = model.addVars(9, 9, 9, vtype=GRB.BINARY, name="x")

# 添加约束：每个格子必须填入一个数字
for i in range(9):
    for j in range(9):
        if board[i][j] != 0:
            # 如果初始值已经存在，固定该格子的值
            model.addConstr(x[i, j, board[i][j] - 1] == 1)
        else:
            # 否则确保该格子被填入一个数字
            model.addConstr(gp.quicksum(x[i, j, k] for k in range(9)) == 1)

# 添加约束：每行不能重复
for i in range(9):
    for k in range(9):
        model.addConstr(gp.quicksum(x[i, j, k] for j in range(9)) == 1)

# 添加约束：每列不能重复
for j in range(9):
    for k in range(9):
        model.addConstr(gp.quicksum(x[i, j, k] for i in range(9)) == 1)

# 添加约束：每个 3x3 小方块内数字不能重复
for block_i in range(3):
    for block_j in range(3):
        for k in range(9):
            model.addConstr(
                gp.quicksum(x[i, j, k]
                            for i in range(3*block_i, 3*block_i + 3)
                            for j in range(3*block_j, 3*block_j + 3)) == 1)

# 设置模型为最小化问题（虽然我们不需要目标函数）
model.setObjective(0, GRB.MINIMIZE)

# 优化模型
model.optimize()

# 打印解
if model.status == GRB.OPTIMAL:
    solution = [[0 for _ in range(9)] for _ in range(9)]
    for i in range(9):
        for j in range(9):
            for k in range(9):
                if x[i, j, k].x > 0.5:  # 如果该变量被设置为 1
                    solution[i][j] = k + 1
    # 打印解出的数独盘面
    for row in solution:
        print(row)
else:
    print("没有找到可行解")
