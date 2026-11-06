# -*- coding: utf-8 -*-
"""Probe the router via UPnP IGD: is there a real public IPv4, or CGNAT/double NAT?"""
import re
import socket
import urllib.request

SSDP = ("M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n")


def ssdp_locations(timeout=3.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    s.settimeout(timeout)
    locs = []
    try:
        s.sendto(SSDP.encode(), ("239.255.255.250", 1900))
        while True:
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                break
            m = re.search(rb"(?i)LOCATION:\s*(\S+)", data)
            if m:
                loc = m.group(1).decode("utf-8", "replace").strip()
                if loc not in locs:
                    locs.append((loc, addr[0]))
    finally:
        s.close()
    return locs


def services(loc):
    xml = urllib.request.urlopen(loc, timeout=5).read().decode("utf-8", "replace")
    base = re.search(r"<URLBase>(.*?)</URLBase>", xml)
    base = base.group(1) if base else re.match(r"(https?://[^/]+)", loc).group(1)
    out = []
    for block in re.findall(r"<service>(.*?)</service>", xml, re.S):
        t = re.search(r"<serviceType>(.*?)</serviceType>", block)
        c = re.search(r"<controlURL>(.*?)</controlURL>", block)
        if t and c:
            url = c.group(1)
            full = url if url.startswith("http") else base + ("/" if not url.startswith("/") else "") + url
            out.append((t.group(1).strip(), full))
    return out


def soap(url, action, stype, args=""):
    body = ('<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            "<s:Body><u:%s xmlns:u=\"%s\">%s</u:%s></s:Body></s:Envelope>"
            % (action, stype, args, action))
    req = urllib.request.Request(url, data=body.encode(),
                                 headers={"Content-Type": 'text/xml; charset="utf-8"',
                                          "SOAPACTION": '"%s#%s"' % (stype, action)})
    return urllib.request.urlopen(req, timeout=6).read().decode("utf-8", "replace")


def main():
    locs = ssdp_locations()
    print("SSDP 找到网关描述: %d 个" % len(locs))
    for loc, ip in locs:
        print("  ", loc, "from", ip)
        try:
            svcs = services(loc)
        except Exception as e:
            print("    读取描述失败:", e)
            continue
        wan = [(t, u) for t, u in svcs if "WANIPConnection" in t or "WANPPPConnection" in t]
        print("    服务数 %d，WAN 连接服务: %d" % (len(svcs), len(wan)))
        for t, u in wan:
            try:
                r = soap(u, "GetExternalIPAddress", t)
                ip = re.search(r"<NewExternalIPAddress>(.*?)</NewExternalIPAddress>", r)
                ip = ip.group(1) if ip else "?"
                r2 = soap(u, "GetStatusInfo", t)
                st = re.search(r"<NewConnectionStatus>(.*?)</NewConnectionStatus>", r2)
                print("    WAN IP =", ip, "| 状态:", st.group(1) if st else "?")
                if ip != "?":
                    a = [int(x) for x in ip.split(".")]
                    if a[0] == 100 and 64 <= a[1] <= 127:
                        print("    => 运营商级 NAT (CGNAT)，端口映射不可能，必须走隧道")
                    elif ip.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.",
                                        "172.2", "172.30.", "172.31.")):
                        print("    => 路由器 WAN 是内网地址（二级 NAT），需要隧道或改光猫桥接")
                    else:
                        print("    => 有公网 IPv4，理论上可以做端口映射")
            except Exception as e:
                print("    SOAP 失败:", repr(e)[:100])


if __name__ == "__main__":
    main()
