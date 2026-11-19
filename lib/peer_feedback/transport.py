# -*- coding: utf-8 -*-
"""HTTP POST of a JSON body -> decoded JSON answer.

In Revit (IronPython) the request goes through .NET HttpWebRequest: it works
the same on .NET Framework 4.8 (Revit 2023-2024) and .NET 8 (Revit 2025+),
uses the Windows proxy settings and needs no extra libraries.
Outside Revit (tests, a check from the command line) urllib is used.

Google Apps Script answers a POST with 302 -> script.googleusercontent.com;
both stacks follow it with a GET, which returns the script's JSON.
Both hosts must be reachable from the office network.
"""

import json


class SendError(Exception):
    """No answer, a non-200 answer or an answer that is not our JSON."""


def _dumps(obj):
    text = json.dumps(obj, ensure_ascii=False)
    if not isinstance(text, type(u'')):
        text = text.decode('utf-8')
    return text


def _parse(text):
    try:
        data = json.loads(text)
    except ValueError:
        # a Google login / error page instead of the script's JSON
        raise SendError(u'not a receiver answer: ' + text[:200])
    if not isinstance(data, dict):
        raise SendError(u'not a receiver answer: ' + text[:200])
    return data


def _post_dotnet(url, body, timeout_s):
    from System.IO import StreamReader
    from System.Net import (WebRequest, WebException,
                            ServicePointManager, SecurityProtocolType,
                            CredentialCache)
    from System.Text import Encoding

    try:
        # Revit 2023-2024 (.NET Framework): make sure TLS 1.2 is on
        ServicePointManager.SecurityProtocol = (
            ServicePointManager.SecurityProtocol | SecurityProtocolType.Tls12)
    except Exception:
        pass

    data = Encoding.UTF8.GetBytes(body)
    req = WebRequest.Create(url)
    req.Method = 'POST'
    req.ContentType = 'text/plain; charset=utf-8'
    req.Timeout = int(timeout_s * 1000)
    req.ReadWriteTimeout = int(timeout_s * 1000)
    req.AllowAutoRedirect = True
    req.UserAgent = 'PEER-feedback'
    try:
        proxy = WebRequest.DefaultWebProxy
        if proxy is not None:
            proxy.Credentials = CredentialCache.DefaultCredentials
            req.Proxy = proxy
    except Exception:
        pass
    req.ContentLength = data.Length
    resp = None
    try:
        stream = req.GetRequestStream()
        try:
            stream.Write(data, 0, data.Length)
        finally:
            stream.Close()
        resp = req.GetResponse()
        reader = StreamReader(resp.GetResponseStream(), Encoding.UTF8)
        try:
            return reader.ReadToEnd()
        finally:
            reader.Close()
    except WebException as ex:
        raise SendError(u'{0}'.format(ex.Message))
    finally:
        if resp is not None:
            resp.Close()


def _post_urllib(url, body, timeout_s):
    try:
        from urllib.request import Request, urlopen
        from urllib.error import URLError
    except ImportError:  # CPython 2
        from urllib2 import Request, urlopen, URLError
    req = Request(url, data=body.encode('utf-8'),
                  headers={'Content-Type': 'text/plain; charset=utf-8',
                           'User-Agent': 'PEER-feedback'})
    try:
        resp = urlopen(req, timeout=timeout_s)
        try:
            return resp.read().decode('utf-8')
        finally:
            resp.close()
    except (URLError, IOError, OSError) as ex:
        raise SendError(u'{0}'.format(ex))


def _has_dotnet():
    try:
        import clr  # noqa: F401
        return True
    except ImportError:
        return False


def post_json(url, obj, timeout_s=10):
    """-> answer dict. Raises SendError on any network / format problem."""
    body = _dumps(obj)
    if _has_dotnet():
        try:
            text = _post_dotnet(url, body, timeout_s)
        except SendError:
            raise
        except Exception as ex:  # .NET exceptions other than WebException
            raise SendError(u'{0}'.format(ex))
    else:
        text = _post_urllib(url, body, timeout_s)
    return _parse(text)
