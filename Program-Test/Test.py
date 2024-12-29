from gurobipy import Model, GRB

# 创建一个新的模型实例
m = Model("production_optimization")

# 定义决策变量
x = m.addVar(vtype=GRB.CONTINUOUS, name="ProductA")
y = m.addVar(vtype=GRB.CONTINUOUS, name="ProductB")

# 设置目标函数：最大化总利润
m.setObjective(10 * x + 6 * y, GRB.MAXIMIZE)

# 添加约束条件
m.addConstr(2 * x + 1 * y <= 100, "Material1")  # 原材料1的限制
m.addConstr(1 * x + 2 * y <= 100, "Material2")  # 原材料2的限制
m.addConstr(3 * x + 3 * y <= 120, "Labor")      # 劳动时间的限制

# 更新模型以包含新添加的变量和约束
m.update()

# 执行优化
m.optimize()

# 输出结果
for v in m.getVars():
    print(f'{v.varName} {v.x}')

print(f'Obj: {m.objVal}')
