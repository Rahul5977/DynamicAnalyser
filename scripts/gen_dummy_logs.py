#!/usr/bin/env python3
"""Generate 5 dummy Wireshark-style analysis log files (2-4 MB each)."""

import random
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..")

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def fmt(func: str, elapsed: float) -> str:
    return f"{func:<48} elapsed={elapsed:.3f}s\n"

def rand_elapsed(lo: float, hi: float) -> float:
    return round(random.uniform(lo, hi), 3)

def write_log(path: str, lines: list[str]) -> None:
    with open(path, "w") as f:
        f.writelines(lines)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"  {os.path.basename(path)}: {len(lines):,} lines, {size_mb:.2f} MB")


# ===========================================================================
# dummy1.log — High-volume TCP/HTTP web-server traffic
#   HOT  (3× per cycle): dissect_tcp
#   COLD (1× total):     dissect_pcapng_block
# ===========================================================================
def gen_dummy1(path: str, target_bytes: int = 3_000_000) -> None:
    lines: list[str] = [
        "# dummy1 — High-volume TCP/HTTP web-server traffic\n",
        "# format: func_name  elapsed=Xs   (matches DynamicAnalyser TsharkParser)\n",
        "# HOT function (3× per cycle): dissect_tcp\n",
        "# COLD function (1× total):    dissect_pcapng_block\n",
        "#\n",
    ]

    # COLD function — called exactly ONCE, right at the start
    lines.append(fmt("dissect_pcapng_block", rand_elapsed(0.001, 0.002)))

    cycle_funcs = [
        ("dissect_frame",            0.001, 0.003),
        ("dissect_eth",              0.001, 0.002),
        ("dissect_ip",               0.002, 0.005),
        # HOT x3 — dissect_tcp appears three times per cycle
        ("dissect_tcp",              0.010, 0.020),
        ("dissect_tcp",              0.008, 0.018),
        ("dissect_tcp",              0.009, 0.019),
        ("tcp_segment_analysis",     0.003, 0.006),
        ("dissect_http",             0.015, 0.030),
        ("dissect_http2",            0.010, 0.025),
        ("dissect_tls",              0.025, 0.060),
        ("tcp_retransmission_analysis", 0.100, 2.500),
        ("out_of_order_segment_check",  0.008, 0.020),
        ("dissect_tcp_payload",      0.004, 0.008),
        ("dissect_vlan",             0.001, 0.002),
        ("dissect_mpls",             0.001, 0.003),
        ("dissect_spnego",           0.008, 0.015),
        ("dissect_kerberos",         0.010, 0.020),
        ("dissect_smb",              0.015, 0.035),
        ("dissect_dcerpc",           0.012, 0.025),
        ("dissect_ldap",             0.010, 0.020),
        ("dissect_snmp",             0.008, 0.015),
        ("dissect_nfs",              0.015, 0.030),
        ("dissect_ssh",              0.010, 0.018),
        ("dissect_mysql",            0.012, 0.022),
        ("dissect_redis",            0.005, 0.012),
        ("dissect_memcache",         0.004, 0.010),
        ("dissect_pgsql",            0.010, 0.020),
    ]

    while sum(len(l.encode()) for l in lines) < target_bytes:
        random.shuffle(cycle_funcs)
        for name, lo, hi in cycle_funcs:
            lines.append(fmt(name, rand_elapsed(lo, hi)))

    write_log(path, lines)


# ===========================================================================
# dummy2.log — 5G NAS / NGAP mobile registration signaling
#   HOT  (2× per cycle): dissect_nas_attach_request
#   COLD (1× total):     dissect_lte_rrc_bcch
# ===========================================================================
def gen_dummy2(path: str, target_bytes: int = 2_500_000) -> None:
    lines: list[str] = [
        "# dummy2 — 5G NAS/NGAP mobile registration signaling\n",
        "# format: func_name  elapsed=Xs   (matches DynamicAnalyser TsharkParser)\n",
        "# HOT function (2× per cycle): dissect_nas_attach_request\n",
        "# COLD function (1× total):    dissect_lte_rrc_bcch\n",
        "#\n",
    ]

    # COLD function — exactly once
    lines.append(fmt("dissect_lte_rrc_bcch", rand_elapsed(0.020, 0.035)))

    cycle_funcs = [
        ("dissect_frame",                    0.001, 0.003),
        ("dissect_eth",                      0.001, 0.002),
        ("dissect_ip",                       0.002, 0.004),
        ("dissect_sctp",                     0.005, 0.010),
        # HOT x2
        ("dissect_nas_attach_request",       0.002, 0.005),
        ("dissect_nas_attach_request",       0.002, 0.005),
        ("dissect_nas_attach_accept",        0.250, 0.350),
        ("dissect_nas_attach_complete",      0.001, 0.003),
        ("dissect_nas_auth_request",         0.100, 0.150),
        ("dissect_nas_auth_response",        0.003, 0.006),
        ("dissect_nas_security_cmd",         0.040, 0.070),
        ("dissect_nas_security_complete",    0.001, 0.003),
        ("dissect_nas_emm_info",             0.002, 0.004),
        ("dissect_nas_detach_request",       0.003, 0.006),
        ("dissect_ngap",                     0.025, 0.045),
        ("dissect_f1ap",                     0.020, 0.038),
        ("dissect_x2ap",                     0.022, 0.040),
        ("dissect_nr_rrc",                   0.030, 0.050),
        ("dissect_lte_rrc_dcch",             0.025, 0.040),
        ("dissect_nb_iot",                   0.028, 0.045),
        ("dissect_e2ap",                     0.018, 0.035),
        ("dissect_gtpv2_create_session",     0.003, 0.006),
        ("dissect_pfcp_session_establishment_request",  0.006, 0.012),
        ("dissect_pfcp_session_establishment_response", 0.005, 0.011),
        ("dissect_pfcp_session_modification_request",   0.005, 0.010),
        ("dissect_pfcp_session_modification_response",  0.004, 0.009),
        ("dissect_pfcp_session_deletion_request",       0.003, 0.007),
        ("dissect_pfcp_session_deletion_response",      0.003, 0.007),
        ("diameter_s6a_air",                 0.002, 0.005),
        ("diameter_s6a_aia",                 0.002, 0.005),
        ("diameter_s6a_ulr",                 0.002, 0.005),
        ("diameter_s6a_ula",                 0.002, 0.005),
        ("diameter_cer",                     0.001, 0.002),
        ("diameter_cea",                     0.001, 0.002),
        ("dissect_eap",                      0.006, 0.012),
        ("dissect_radius",                   0.008, 0.015),
    ]

    while sum(len(l.encode()) for l in lines) < target_bytes:
        random.shuffle(cycle_funcs)
        for name, lo, hi in cycle_funcs:
            lines.append(fmt(name, rand_elapsed(lo, hi)))

    write_log(path, lines)


# ===========================================================================
# dummy3.log — VoIP / SIP / RTP call-processing
#   HOT  (3× per cycle): dissect_rtp
#   COLD (1× total):     dissect_isup_anm
# ===========================================================================
def gen_dummy3(path: str, target_bytes: int = 3_500_000) -> None:
    lines: list[str] = [
        "# dummy3 — VoIP / SIP / RTP call-processing\n",
        "# format: func_name  elapsed=Xs   (matches DynamicAnalyser TsharkParser)\n",
        "# HOT function (3× per cycle): dissect_rtp\n",
        "# COLD function (1× total):    dissect_isup_anm\n",
        "#\n",
    ]

    # COLD — exactly once
    lines.append(fmt("dissect_isup_anm", rand_elapsed(0.010, 0.018)))

    cycle_funcs = [
        ("dissect_frame",            0.001, 0.003),
        ("dissect_eth",              0.001, 0.002),
        ("dissect_ip",               0.002, 0.004),
        ("dissect_udp",              0.001, 0.003),
        # HOT x3
        ("dissect_rtp",              0.008, 0.015),
        ("dissect_rtp",              0.007, 0.014),
        ("dissect_rtp",              0.009, 0.016),
        ("dissect_rtcp",             0.007, 0.013),
        ("dissect_sdp",              0.010, 0.020),
        ("dissect_sip_invite",       0.020, 0.035),
        ("dissect_sip_response",     0.015, 0.025),
        ("dissect_sip_register",     0.015, 0.025),
        ("dissect_stun",             0.005, 0.010),
        ("dissect_turn",             0.006, 0.012),
        ("dissect_h248",             0.018, 0.030),
        ("dissect_isup_iam",         0.012, 0.020),
        ("dissect_isup_acm",         0.010, 0.017),
        ("dissect_gsm_map",          0.015, 0.028),
        ("dissect_bssap",            0.013, 0.022),
        ("dissect_cap",              0.014, 0.024),
        ("dissect_inap",             0.015, 0.025),
        ("dissect_quic",             0.035, 0.060),
        ("dissect_tls",              0.025, 0.050),
        ("dissect_sctp",             0.005, 0.010),
        ("dissect_coap",             0.007, 0.013),
        ("dissect_mqtt",             0.006, 0.012),
        ("dissect_amqp",             0.008, 0.016),
        ("dissect_kafka",            0.010, 0.020),
        ("dissect_dhcp",             0.007, 0.014),
        ("dissect_dns",              0.006, 0.012),
        ("dns_retransmission_analysis", 0.015, 0.030),
    ]

    while sum(len(l.encode()) for l in lines) < target_bytes:
        random.shuffle(cycle_funcs)
        for name, lo, hi in cycle_funcs:
            lines.append(fmt(name, rand_elapsed(lo, hi)))

    write_log(path, lines)


# ===========================================================================
# dummy4.log — GTPv2 / PFCP EPC data-plane session management
#   HOT  (2× per cycle): gtpv2_create_session_request
#   COLD (1× total):     dissect_gtp_prime
# ===========================================================================
def gen_dummy4(path: str, target_bytes: int = 2_200_000) -> None:
    lines: list[str] = [
        "# dummy4 — GTPv2 / PFCP EPC data-plane session management\n",
        "# format: func_name  elapsed=Xs   (matches DynamicAnalyser TsharkParser)\n",
        "# HOT function (2× per cycle): gtpv2_create_session_request\n",
        "# COLD function (1× total):    dissect_gtp_prime\n",
        "#\n",
    ]

    # COLD — exactly once
    lines.append(fmt("dissect_gtp_prime", rand_elapsed(0.006, 0.010)))

    cycle_funcs = [
        ("dissect_frame",                               0.001, 0.003),
        ("dissect_eth",                                 0.001, 0.002),
        ("dissect_ip",                                  0.002, 0.004),
        ("dissect_udp",                                 0.001, 0.003),
        # HOT x2
        ("gtpv2_create_session_request",                0.003, 0.006),
        ("gtpv2_create_session_request",                0.003, 0.006),
        ("gtpv2_create_session_response",               0.003, 0.006),
        ("gtpv2_modify_bearer_request",                 0.002, 0.005),
        ("gtpv2_modify_bearer_response",                0.002, 0.005),
        ("gtpv2_delete_session_request",                0.002, 0.005),
        ("gtpv2_delete_session_response",               0.002, 0.005),
        ("gtpv2_echo_request",                          0.001, 0.002),
        ("gtpv2_echo_response",                         0.001, 0.002),
        ("gtpv2_release_access_bearers_request",        0.002, 0.005),
        ("gtpv2_release_access_bearers_response",       0.002, 0.005),
        ("dissect_pfcp_pfd_management_request",         0.004, 0.008),
        ("dissect_pfcp_session_establishment_request",  0.006, 0.012),
        ("dissect_pfcp_session_establishment_response", 0.005, 0.011),
        ("dissect_pfcp_session_modification_request",   0.005, 0.010),
        ("dissect_pfcp_session_modification_response",  0.004, 0.009),
        ("dissect_pfcp_session_deletion_request",       0.003, 0.007),
        ("dissect_pfcp_session_deletion_response",      0.003, 0.007),
        ("dissect_gtp_v1",                              0.005, 0.010),
        ("dissect_sctp",                                0.004, 0.009),
        ("dissect_diameter_base",                       0.003, 0.007),
        ("diameter_ccr",                                0.002, 0.005),
        ("diameter_cca",                                0.002, 0.005),
        ("diameter_gx_ccr",                             0.003, 0.006),
        ("diameter_gx_cca",                             0.003, 0.006),
        ("diameter_ulr",                                0.002, 0.004),
        ("diameter_ula",                                0.002, 0.004),
        ("diameter_air",                                0.002, 0.004),
        ("diameter_aia",                                0.002, 0.004),
        ("diameter_s6a_clr",                            0.002, 0.004),
        ("diameter_s6a_cla",                            0.002, 0.004),
        ("diameter_s6a_idr",                            0.002, 0.004),
        ("diameter_s6a_ida",                            0.002, 0.004),
        ("diameter_s6a_dsr",                            0.002, 0.004),
        ("diameter_s6a_dsa",                            0.002, 0.004),
        ("dissect_radius",                              0.008, 0.015),
        ("dissect_dhcp",                                0.007, 0.013),
        ("dissect_arp",                                 0.001, 0.003),
        ("dissect_vlan",                                0.001, 0.002),
        ("dissect_ipv6",                                0.002, 0.005),
        ("dissect_icmp",                                0.002, 0.004),
        ("dissect_icmpv6",                              0.002, 0.004),
    ]

    while sum(len(l.encode()) for l in lines) < target_bytes:
        random.shuffle(cycle_funcs)
        for name, lo, hi in cycle_funcs:
            lines.append(fmt(name, rand_elapsed(lo, hi)))

    write_log(path, lines)


# ===========================================================================
# dummy5.log — Security-focused: TLS / QUIC / IPSec / VPN / routing
#   HOT  (3× per cycle): dissect_tls
#   COLD (1× total):     dissect_wireguard
# ===========================================================================
def gen_dummy5(path: str, target_bytes: int = 3_800_000) -> None:
    lines: list[str] = [
        "# dummy5 — Security-focused: TLS / QUIC / IPSec / VPN / routing\n",
        "# format: func_name  elapsed=Xs   (matches DynamicAnalyser TsharkParser)\n",
        "# HOT function (3× per cycle): dissect_tls\n",
        "# COLD function (1× total):    dissect_wireguard\n",
        "#\n",
    ]

    # COLD — exactly once
    lines.append(fmt("dissect_wireguard", rand_elapsed(0.010, 0.016)))

    cycle_funcs = [
        ("dissect_frame",            0.001, 0.003),
        ("dissect_eth",              0.001, 0.002),
        ("dissect_ip",               0.002, 0.004),
        ("dissect_ipv6",             0.002, 0.005),
        ("dissect_tcp",              0.010, 0.020),
        ("dissect_udp",              0.001, 0.003),
        # HOT x3
        ("dissect_tls",              0.025, 0.060),
        ("dissect_tls",              0.020, 0.055),
        ("dissect_tls",              0.022, 0.058),
        ("dissect_quic",             0.035, 0.065),
        ("dissect_ipsec_esp",        0.007, 0.014),
        ("dissect_ipsec_ah",         0.006, 0.012),
        ("dissect_openvpn",          0.010, 0.020),
        ("dissect_gre",              0.002, 0.005),
        ("dissect_ppp",              0.002, 0.005),
        ("dissect_pppoe",            0.003, 0.006),
        ("dissect_l2tp",             0.009, 0.018),
        ("dissect_pptp",             0.008, 0.016),
        ("dissect_eap",              0.006, 0.012),
        ("dissect_radius",           0.008, 0.016),
        ("dissect_kerberos",         0.010, 0.020),
        ("dissect_spnego",           0.008, 0.016),
        ("dissect_ldap",             0.010, 0.020),
        ("dissect_ntlm",             0.009, 0.018),
        ("dissect_ssh",              0.010, 0.020),
        ("dissect_http",             0.015, 0.030),
        ("dissect_http2",            0.012, 0.025),
        ("dissect_bgp",              0.025, 0.045),
        ("dissect_ospf",             0.015, 0.025),
        ("dissect_isis",             0.015, 0.028),
        ("dissect_eigrp",            0.012, 0.022),
        ("dissect_rip",              0.007, 0.014),
        ("dissect_vrrp",             0.004, 0.009),
        ("dissect_hsrp",             0.005, 0.010),
        ("dissect_lacp",             0.002, 0.005),
        ("dissect_stp",              0.002, 0.004),
        ("dissect_lldp",             0.004, 0.009),
        ("dissect_cdp",              0.003, 0.007),
        ("dissect_dns",              0.006, 0.012),
        ("dissect_ntp",              0.004, 0.008),
        ("dissect_snmp",             0.008, 0.016),
        ("dissect_syslog",           0.004, 0.009),
        ("dissect_dhcp",             0.007, 0.014),
        ("dissect_dhcpv6",           0.008, 0.015),
        ("dissect_arp",              0.001, 0.003),
        ("dissect_icmp",             0.002, 0.004),
        ("dissect_icmpv6",           0.002, 0.004),
        ("tcp_retransmission_analysis", 0.080, 1.800),
        ("out_of_order_segment_check",  0.008, 0.020),
        ("dissect_stun",             0.005, 0.010),
        ("dissect_turn",             0.006, 0.012),
        ("dissect_vlan",             0.001, 0.002),
        ("dissect_mpls",             0.001, 0.003),
        ("dissect_llc",              0.001, 0.002),
    ]

    while sum(len(l.encode()) for l in lines) < target_bytes:
        random.shuffle(cycle_funcs)
        for name, lo, hi in cycle_funcs:
            lines.append(fmt(name, rand_elapsed(lo, hi)))

    write_log(path, lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    random.seed(42)

    configs = [
        ("dummy1.log", gen_dummy1, 3_000_000),
        ("dummy2.log", gen_dummy2, 2_500_000),
        ("dummy3.log", gen_dummy3, 3_500_000),
        ("dummy4.log", gen_dummy4, 2_200_000),
        ("dummy5.log", gen_dummy5, 3_800_000),
    ]

    print("Generating dummy log files...")
    for fname, generator, target in configs:
        out_path = os.path.join(OUTPUT_DIR, fname)
        generator(out_path, target)

    print("Done.")
