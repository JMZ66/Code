import gurobipy as gp
from gurobipy import GRB

# 数据示例
volumes = [0.5, 0.3, 1.2]  # 药品体积（升）
demands = [50, 30, 40]  # 药品需求量，按包装数量
capacities = [1000, 800]  # 运输工具容量（升）
transport_times = [[1, 2], [1.5, 2.5], [2, 3]]  # 各药品在不同运输工具上的时间（小时）

# 不兼容药品矩阵 (药品1和药品3不能一起运输)
incompatibility_matrix = [[0, 0, 1],  # 药品0与药品2不兼容
                          [0, 0, 0],  # 药品1与其他药品兼容
                          [1, 0, 0]]  # 药品2与药品0不兼容

# 搬运组数量
num_teams = 2  # 两组搬运人员

# 创建模型
model = gp.Model("Complex搬迁_with_incompatibility")

# 决策变量：每种药品是否由某组搬运人员使用某运输工具搬运
z = model.addVars(len(demands), len(capacities), num_teams, vtype=GRB.BINARY, name="z")

# 时间变量：每组搬运人员在每个运输工具上的起始和结束时间
T_start = model.addVars(len(capacities), num_teams, vtype=GRB.CONTINUOUS, name="T_start")
T_end = model.addVars(len(capacities), num_teams, vtype=GRB.CONTINUOUS, name="T_end")

# 目标函数：最小化最晚完成的时间
max_end_time = model.addVar(vtype=GRB.CONTINUOUS, name="max_end_time")
model.setObjective(max_end_time, GRB.MINIMIZE)

# 约束1：满足每种药品的需求量，按瓶、包、箱来计算
for i in range(len(demands)):
    model.addConstr(gp.quicksum(z[i,k,m] for k in range(len(capacities)) for m in range(num_teams)) == demands[i], name=f"demand_{i}")

# 约束2：运输工具的容量限制（体积以升为单位）
for k in range(len(capacities)):
    for m in range(num_teams):
        model.addConstr(gp.quicksum(z[i,k,m] * volumes[i] for i in range(len(demands))) <= capacities[k], name=f"capacity_{k}_team_{m}")

# 约束3：不兼容性约束（根据incompatibility_matrix，确保不兼容药品不会一起被装载）
for i in range(len(demands)):
    for j in range(i + 1, len(demands)):  # 只需要检查 i < j 的不兼容组合
        if incompatibility_matrix[i][j] == 1:  # 如果 i 和 j 不能一起运输
            for k in range(len(capacities)):
                for m in range(num_teams):
                    # 确保不兼容的药品不会被同一组在同一运输工具上运输
                    model.addConstr(z[i,k,m] + z[j,k,m] <= 1, name=f"incompatible_{i}_{j}_{k}_team_{m}")

# 约束4：每个搬运组在同一时间只能执行一个任务
for m in range(num_teams):
    for k1 in range(len(capacities)):
        for k2 in range(k1 + 1, len(capacities)):
            for i in range(len(demands)):
                model.addConstr(T_start[k1, m] >= T_end[k2, m] * z[i, k2, m] + (1 - z[i, k2, m]) * -GRB.INFINITY, name=f"team_{m}_task_time_{k1}_{k2}")
                model.addConstr(T_start[k2, m] >= T_end[k1, m] * z[i, k1, m] + (1 - z[i, k1, m]) * -GRB.INFINITY, name=f"team_{m}_task_time_{k2}_{k1}")

# 约束5：时间约束（运输时间）
for k in range(len(capacities)):
    for m in range(num_teams):
        for i in range(len(demands)):
            model.addConstr(T_end[k, m] >= T_start[k, m] + z[i, k, m] * transport_times[i][k], name=f"time_{i}_{k}_team_{m}")

# 约束6：最晚结束时间的定义
for k in range(len(capacities)):
    for m in range(num_teams):
        model.addConstr(max_end_time >= T_end[k, m], name=f"max_end_time_constraint_{k}_team_{m}")

# 求解模型
model.optimize()

# 输出解
if model.status == GRB.OPTIMAL:
    for i in range(len(demands)):
        for k in range(len(capacities)):
            for m in range(num_teams):
                if z[i,k,m].x > 0.5:
                    print(f"药品 {i+1} 由搬运组 {m+1} 使用运输工具 {k+1} 运输")
    print(f"最晚结束时间: {max_end_time.x}")
else:
    print("没有找到可行解")
