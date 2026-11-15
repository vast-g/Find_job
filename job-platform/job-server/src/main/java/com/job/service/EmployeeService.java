package com.job.service;

import com.job.dto.EmployeeDTO;
import com.job.dto.EmployeeLoginDTO;
import com.job.dto.EmployeePageQueryDTO;
import com.job.entity.Employee;
import com.job.result.PageResult;

public interface EmployeeService {

    Employee login(EmployeeLoginDTO employeeLoginDTO);

    void save(EmployeeDTO employeeDTO);

    PageResult pageQuery(EmployeePageQueryDTO employeePageQueryDTO);

    void startOrStop(Integer status, Long id);

    Employee getById(Long id);

    void update(EmployeeDTO employeeDTO);
}
