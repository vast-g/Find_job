package com.job.aspect;

import com.job.annotation.AutoFill;
import com.job.constant.AutoFillConstant;
import com.job.context.BaseContext;
import com.job.enumeration.OperationType;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.JoinPoint;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.annotation.Before;
import org.aspectj.lang.annotation.Pointcut;
import org.aspectj.lang.reflect.MethodSignature;
import org.springframework.stereotype.Component;

import java.lang.reflect.Method;
import java.time.LocalDateTime;

/**
 * 公共字段自动填充切面
 */
@Aspect
@Component
@Slf4j
public class AutoFillAspect {

    @Pointcut("execution(* com.job.mapper.*.*(..)) && @annotation(com.job.annotation.AutoFill)")
    public void autoFillPointCut() {
    }

    @Before("autoFillPointCut()")
    public void autoFill(JoinPoint joinPoint) throws Exception {
        MethodSignature signature = (MethodSignature) joinPoint.getSignature();
        AutoFill autoFill = signature.getMethod().getAnnotation(AutoFill.class);
        OperationType operationType = autoFill.value();

        Object[] args = joinPoint.getArgs();
        if (args == null || args.length == 0) {
            return;
        }
        Object entity = args[0];

        LocalDateTime now = LocalDateTime.now();
        Long currentId = BaseContext.getCurrentId();

        if (operationType == OperationType.INSERT) {
            setValue(entity, AutoFillConstant.SET_CREATE_TIME, LocalDateTime.class, now);
            setValue(entity, AutoFillConstant.SET_UPDATE_TIME, LocalDateTime.class, now);
            setValue(entity, AutoFillConstant.SET_CREATE_USER, Long.class, currentId);
            setValue(entity, AutoFillConstant.SET_UPDATE_USER, Long.class, currentId);
        } else if (operationType == OperationType.UPDATE) {
            setValue(entity, AutoFillConstant.SET_UPDATE_TIME, LocalDateTime.class, now);
            setValue(entity, AutoFillConstant.SET_UPDATE_USER, Long.class, currentId);
        }
    }

    private void setValue(Object entity, String methodName, Class<?> paramType, Object value) throws Exception {
        try {
            Method method = entity.getClass().getDeclaredMethod(methodName, paramType);
            method.invoke(entity, value);
        } catch (NoSuchMethodException e) {
            // 实体没有该字段时跳过
        }
    }
}
