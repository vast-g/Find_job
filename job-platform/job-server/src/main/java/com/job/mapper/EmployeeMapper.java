package com.job.mapper;

import com.github.pagehelper.Page;
import com.job.annotation.AutoFill;
import com.job.dto.EmployeePageQueryDTO;
import com.job.entity.Employee;
import com.job.enumeration.OperationType;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface EmployeeMapper {

    @Select("select * from employee where username = #{username}")
    Employee getByUsername(String username);

    @AutoFill(OperationType.INSERT)
    void insert(Employee employee);

    Page<Employee> pageQuery(EmployeePageQueryDTO employeePageQueryDTO);

    @Select("select * from employee where id = #{id}")
    Employee getById(Long id);

    @AutoFill(OperationType.UPDATE)
    void update(Employee employee);
}
