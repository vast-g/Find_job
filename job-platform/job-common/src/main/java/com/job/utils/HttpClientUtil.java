package com.job.utils;

import com.alibaba.fastjson.JSONObject;
import org.apache.http.NameValuePair;
import org.apache.http.client.config.RequestConfig;
import org.apache.http.client.entity.UrlEncodedFormEntity;
import org.apache.http.client.methods.CloseableHttpResponse;
import org.apache.http.client.methods.HttpGet;
import org.apache.http.client.methods.HttpPost;
import org.apache.http.client.utils.URIBuilder;
import org.apache.http.entity.StringEntity;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClients;
import org.apache.http.message.BasicNameValuePair;
import org.apache.http.util.EntityUtils;

import java.io.IOException;
import java.net.URI;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * HTTP 工具类
 */
public class HttpClientUtil {

    static final int TIMEOUT_MSEC = 5 * 1000;
    /** Agent 本地 CPU 推理较慢（50~120s），需要单独的长超时 */
    static final int AGENT_TIMEOUT_MSEC = 180 * 1000;

    public static String doGet(String url, Map<String, String> paramMap) {
        CloseableHttpClient httpClient = HttpClients.createDefault();
        String result = "";
        CloseableHttpResponse response = null;
        try {
            URIBuilder builder = new URIBuilder(url);
            if (paramMap != null) {
                for (String key : paramMap.keySet()) {
                    builder.addParameter(key, paramMap.get(key));
                }
            }
            URI uri = builder.build();
            HttpGet httpGet = new HttpGet(uri);
            response = httpClient.execute(httpGet);
            if (response.getStatusLine().getStatusCode() == 200) {
                result = EntityUtils.toString(response.getEntity(), "UTF-8");
            }
        } catch (Exception e) {
            e.printStackTrace();
        } finally {
            close(response, httpClient);
        }
        return result;
    }

    /**
     * GET 请求，支持自定义请求头（如 Referer、X-Requested-With）
     */
    public static String doGetWithHeaders(String url, Map<String, String> paramMap, Map<String, String> headers) {
        CloseableHttpClient httpClient = HttpClients.createDefault();
        String result = "";
        CloseableHttpResponse response = null;
        try {
            URIBuilder builder = new URIBuilder(url);
            if (paramMap != null) {
                for (String key : paramMap.keySet()) {
                    builder.addParameter(key, paramMap.get(key));
                }
            }
            URI uri = builder.build();
            HttpGet httpGet = new HttpGet(uri);
            if (headers != null) {
                for (Map.Entry<String, String> e : headers.entrySet()) {
                    httpGet.setHeader(e.getKey(), e.getValue());
                }
            }
            response = httpClient.execute(httpGet);
            if (response.getStatusLine().getStatusCode() == 200) {
                result = EntityUtils.toString(response.getEntity(), "UTF-8");
            }
        } catch (Exception e) {
            e.printStackTrace();
        } finally {
            close(response, httpClient);
        }
        return result;
    }

    /**
     * POST 请求，发送原始 JSON 字符串 + 自定义请求头
     */
    public static String doPostJsonWithHeaders(String url, String jsonBody, Map<String, String> headers) {
        CloseableHttpClient httpClient = HttpClients.createDefault();
        String result = "";
        CloseableHttpResponse response = null;
        try {
            HttpPost httpPost = new HttpPost(url);
            httpPost.setHeader("Content-Type", "application/json");
            if (headers != null) {
                for (Map.Entry<String, String> e : headers.entrySet()) {
                    httpPost.setHeader(e.getKey(), e.getValue());
                }
            }
            if (jsonBody != null) {
                StringEntity entity = new StringEntity(jsonBody, "utf-8");
                entity.setContentEncoding("utf-8");
                entity.setContentType("application/json");
                httpPost.setEntity(entity);
            }
            response = httpClient.execute(httpPost);
            if (response.getStatusLine().getStatusCode() == 200) {
                result = EntityUtils.toString(response.getEntity(), "UTF-8");
            }
        } catch (Exception e) {
            e.printStackTrace();
        } finally {
            close(response, httpClient);
        }
        return result;
    }

    public static String doPost(String url, Map<String, String> paramMap) throws IOException {
        CloseableHttpClient httpClient = HttpClients.createDefault();
        CloseableHttpResponse response = null;
        String resultString = "";
        try {
            HttpPost httpPost = new HttpPost(url);
            if (paramMap != null) {
                List<NameValuePair> paramList = new ArrayList<>();
                for (Map.Entry<String, String> param : paramMap.entrySet()) {
                    paramList.add(new BasicNameValuePair(param.getKey(), param.getValue()));
                }
                httpPost.setEntity(new UrlEncodedFormEntity(paramList));
            }
            httpPost.setConfig(builderRequestConfig());
            response = httpClient.execute(httpPost);
            resultString = EntityUtils.toString(response.getEntity(), "UTF-8");
        } catch (Exception e) {
            throw e;
        } finally {
            close(response, httpClient);
        }
        return resultString;
    }

    public static String doPost4Json(String url, Map<String, String> paramMap) throws IOException {
        CloseableHttpClient httpClient = HttpClients.createDefault();
        CloseableHttpResponse response = null;
        String resultString = "";
        try {
            HttpPost httpPost = new HttpPost(url);
            if (paramMap != null) {
                JSONObject jsonObject = new JSONObject();
                for (Map.Entry<String, String> param : paramMap.entrySet()) {
                    jsonObject.put(param.getKey(), param.getValue());
                }
                StringEntity entity = new StringEntity(jsonObject.toString(), "utf-8");
                entity.setContentEncoding("utf-8");
                entity.setContentType("application/json");
                httpPost.setEntity(entity);
            }
            httpPost.setConfig(builderRequestConfig());
            response = httpClient.execute(httpPost);
            resultString = EntityUtils.toString(response.getEntity(), "UTF-8");
        } catch (Exception e) {
            throw e;
        } finally {
            close(response, httpClient);
        }
        return resultString;
    }

    /**
     * POST 原始 JSON 字符串
     */
    public static String doPostJson(String url, String jsonBody) throws IOException {
        CloseableHttpClient httpClient = HttpClients.createDefault();
        CloseableHttpResponse response = null;
        String resultString = "";
        try {
            HttpPost httpPost = new HttpPost(url);
            StringEntity entity = new StringEntity(jsonBody, "utf-8");
            entity.setContentEncoding("utf-8");
            entity.setContentType("application/json");
            httpPost.setEntity(entity);
            // Agent 本地 CPU 推理较慢（50~120s），使用长超时，避免 5s 就断开报「暂不可用」
            httpPost.setConfig(builderRequestConfig(AGENT_TIMEOUT_MSEC));
            response = httpClient.execute(httpPost);
            resultString = EntityUtils.toString(response.getEntity(), "UTF-8");
        } catch (Exception e) {
            throw e;
        } finally {
            close(response, httpClient);
        }
        return resultString;
    }

    private static RequestConfig builderRequestConfig() {
        return builderRequestConfig(TIMEOUT_MSEC);
    }

    private static RequestConfig builderRequestConfig(int timeoutMsec) {
        return RequestConfig.custom()
                .setConnectTimeout(timeoutMsec)
                .setConnectionRequestTimeout(timeoutMsec)
                .setSocketTimeout(timeoutMsec)
                .build();
    }

    private static void close(CloseableHttpResponse response, CloseableHttpClient httpClient) {
        try {
            if (response != null) {
                response.close();
            }
            httpClient.close();
        } catch (IOException e) {
            e.printStackTrace();
        }
    }
}
