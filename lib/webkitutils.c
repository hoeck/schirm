
/*
 *Implements methods which are not available through pywebkitgtk.
 */


#include <Python.h>
#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include <glib.h>
#include <webkit/webkit.h>
#include <libsoup/soup.h>
#include <JavaScriptCore/JavaScript.h>

static PyObject *
webkitutils_set_proxy(PyObject *obj, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"proxy_uri", 0};
    const char *uri;
    SoupSession *session;
    SoupURI *proxy_uri;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s", kwlist, &uri))
        return NULL;

    proxy_uri = soup_uri_new(uri);
    if (!proxy_uri) {
        PyErr_SetString(PyExc_ValueError, "malformed proxy uri");
        return NULL;
    }
    session = webkit_get_default_session();
    g_object_set(session, "proxy-uri", proxy_uri, NULL);
    soup_uri_free(proxy_uri);
    
    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject *
webkitutils_eval_js(PyObject *self, PyObject *args) {

  const char *frame_name;
  const char *script;
  const char *uri;
  PyObject *py_context;

  if (!PyArg_ParseTuple(args, "Oss", &py_context, &uri, &script))
    return NULL;

  JSGlobalContextRef context;
  JSObjectRef globalobject;
  JSStringRef js_file;
  JSStringRef js_script;
  JSValueRef js_result;
  JSValueRef js_exc = NULL;
  JSStringRef js_result_string;
  GString *result = g_string_new(NULL);
  size_t js_result_size;

  context = PyCObject_AsVoidPtr(py_context);
  globalobject = JSContextGetGlobalObject(context);

  /* evaluate the script and get return value*/
  js_script = JSStringCreateWithUTF8CString(script);
  js_file = JSStringCreateWithUTF8CString(uri);
  js_result = JSEvaluateScript(context, js_script, globalobject, js_file, 0, &js_exc);
  if (js_result && !JSValueIsUndefined(context, js_result)) {
    js_result_string = JSValueToStringCopy(context, js_result, NULL);
    js_result_size = JSStringGetMaximumUTF8CStringSize(js_result_string);

    if (js_result_size) {
      gchar js_result_utf8[js_result_size];
      JSStringGetUTF8CString(js_result_string, js_result_utf8, js_result_size);
      g_string_assign(result, js_result_utf8);
    }

    JSStringRelease(js_result_string);
  }
  else if (js_exc) {
    size_t size;
    JSStringRef prop, val;
    JSObjectRef exc = JSValueToObject(context, js_exc, NULL);

    g_printf("Exception occured while executing script:\n");

    /* Print file */
    prop = JSStringCreateWithUTF8CString("sourceURL");
    val = JSValueToStringCopy(context, JSObjectGetProperty(context, exc, prop, NULL), NULL);
    size = JSStringGetMaximumUTF8CStringSize(val);
    if(size) {
      gchar cstr[size];
      JSStringGetUTF8CString(val, cstr, size);
      g_printf("At %s", cstr);
    }
    JSStringRelease(prop);
    JSStringRelease(val);
    
    /* Print line */
    prop = JSStringCreateWithUTF8CString("line");
    val = JSValueToStringCopy(context, JSObjectGetProperty(context, exc, prop, NULL), NULL);
    size = JSStringGetMaximumUTF8CStringSize(val);
    if(size) {
      gchar cstr[size];
      JSStringGetUTF8CString(val, cstr, size);
      g_printf(":%s: ", cstr);
    }
    JSStringRelease(prop);
    JSStringRelease(val);
    
    /* Print message */
    val = JSValueToStringCopy(context, exc, NULL);
    size = JSStringGetMaximumUTF8CStringSize(val);
    if(size) {
      gchar cstr[size];
      JSStringGetUTF8CString(val, cstr, size);
      g_printf("%s\n", cstr);
    }
    JSStringRelease(val);
  }

  /* cleanup */
  JSStringRelease(js_script);
  JSStringRelease(js_file);

  return Py_BuildValue("s", g_string_free(result, FALSE));
}

static PyMethodDef WebkitutilsMethods[] = {

    {"set_proxy", webkitutils_set_proxy, METH_VARARGS | METH_KEYWORDS,
     "Set the proxy for the default webkit session."},

    {"eval_js", webkitutils_eval_js, METH_VARARGS,
     "Evaluate a script in the given javascript context."},

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

PyMODINIT_FUNC
initwebkitutils(void) {
    (void) Py_InitModule("webkitutils", WebkitutilsMethods);
}
