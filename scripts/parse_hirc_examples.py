# Dumps HIRC examples from Banks1.pck for documentation.
import struct
import sys

PATH = r'C:\Program Files\HoYoPlay\games\Genshin Impact game\GenshinImpact_Data\StreamingAssets\AudioAssets\Banks1.pck'

PN = {
    0x00: 'Volume', 0x01: 'LFE', 0x02: 'Pitch', 0x03: 'LPF', 0x04: 'HPF',
    0x05: 'BusVolume', 0x06: 'MakeUpGain', 0x07: 'Priority',
    0x08: 'PriorityDistOff', 0x0B: 'InitialDelay', 0x0D: 'TransitionTime',
    0x0E: 'Probability', 0x14: 'UserAuxSend0', 0x17: 'GameAuxSendVol',
    0x18: 'OutputBusVol', 0x19: 'OutputBusHPF', 0x1A: 'OutputBusLPF',
}
AT = {1: 'Stop', 2: 'Pause', 3: 'Resume', 4: 'Play', 8: 'Mute', 9: 'UnMute',
      16: 'SetState', 18: 'SetSwitch', 25: 'SetBusVolume'}
RS = {0: 'RandomContinuous', 1: 'SequentialContinuous',
      2: 'RandomStep', 3: 'SequentialStep'}
STN = ['InMemory', 'Prefetch', 'Streaming']


def pprop(d, off):
    c = d[off]; off += 1
    if c == 0:
        return off, '(vuoto)'
    ids = [d[off + i] for i in range(c)]; off += c
    parts = []
    for i in range(c):
        fv = struct.unpack_from('<f', d, off)[0]; off += 4
        parts.append('%s=%.3f' % (PN.get(ids[i], '0x%02X' % ids[i]), fv))
    return off, ', '.join(parts)


def pranged(d, off):
    c = d[off]; off += 1
    if c == 0:
        return off, '(vuoto)'
    ids = [d[off + i] for i in range(c)]; off += c
    parts = []
    for i in range(c):
        mn = struct.unpack_from('<f', d, off)[0]; off += 4
        mx = struct.unpack_from('<f', d, off)[0]; off += 4
        parts.append('%s:[%.2f,%.2f]' % (PN.get(ids[i], '?'), mn, mx))
    return off, ', '.join(parts)


def main():
    with open(PATH, 'rb') as f:
        data = f.read()

    # ===== 0x01 Settings/State =====
    print('=' * 60)
    print('TYPE 0x01 - Settings / State')
    print('=' * 60)
    o = 0x000154D1
    d = data[o:]; sl = struct.unpack_from('<I', d, 1)[0]; d = d[:5 + sl]; off = 5
    oid = struct.unpack_from('<I', d, off)[0]; off += 4
    print('  objID=0x%08X  secLen=%d' % (oid, sl))
    # State objects: objID + numProps(u8) + [propID(u8) + accumType(u8) + value(f64)] per prop
    nprops = d[off]; off += 1
    print('  numStateProps=%d' % nprops)
    for i in range(nprops):
        if off + 10 > len(d):
            break
        spid = d[off]; off += 1
        acc = d[off]; off += 1
        val = struct.unpack_from('<d', d, off)[0]; off += 8
        print('    [%d] propID=0x%02X accumType=%d value=%.4f' % (i, spid, acc, val))
    print()

    # ===== 0x02 Sound SFX =====
    print('=' * 60)
    print('TYPE 0x02 - Sound SFX')
    print('=' * 60)
    o = 0x0006BCCD
    d = data[o:]; sl = struct.unpack_from('<I', d, 1)[0]; d = d[:5 + sl]; off = 5
    oid = struct.unpack_from('<I', d, off)[0]; off += 4
    pid = struct.unpack_from('<I', d, off)[0]; off += 4
    st = d[off]; off += 1
    sid = struct.unpack_from('<I', d, off)[0]; off += 4
    msz = struct.unpack_from('<I', d, off)[0]; off += 4
    sb = d[off]; off += 1
    print('  objID=0x%08X' % oid)
    print('  BankSourceData:')
    print('    pluginID=0x%08X  streamType=%d (%s)' % (pid, st, STN[st]))
    print('    sourceID=0x%08X  mediaSize=%d  sourceBits=0x%02X' % (sid, msz, sb))
    bov = d[off]; off += 1; nfx = d[off]; off += 1
    bat = d[off]; off += 1
    busId = struct.unpack_from('<I', d, off)[0]; off += 4
    par = struct.unpack_from('<I', d, off)[0]; off += 4
    bv = d[off]; off += 1
    print('  NodeBaseParams:')
    print('    bIsOverrideParentFX=%d  uNumFx=%d' % (bov, nfx))
    print('    bOverrideAttachmentParams=%d' % bat)
    print('    overrideBusID=0x%08X' % busId)
    print('    directParentID=0x%08X' % par)
    print('    byBitVector=0x%02X' % bv)
    off, s = pprop(d, off); print('    PropBundle: %s' % s)
    off, s = pranged(d, off); print('    RangedModifiers: %s' % s)
    print('  [remaining %d bytes: positioning, aux, etc.]' % (len(d) - off))
    print()

    # ===== 0x03 Event Action =====
    print('=' * 60)
    print('TYPE 0x03 - Event Action')
    print('=' * 60)
    o = 0x000287F5
    d = data[o:]; sl = struct.unpack_from('<I', d, 1)[0]; d = d[:5 + sl]; off = 5
    oid = struct.unpack_from('<I', d, off)[0]; off += 4
    scope = d[off]; off += 1
    atype = d[off]; off += 1
    tid = struct.unpack_from('<I', d, off)[0]; off += 4
    print('  objID=0x%08X' % oid)
    print('  scope=%d  actionType=%d (%s)' % (scope, atype, AT.get(atype, '?')))
    print('  targetID=0x%08X' % tid)
    print('  [remaining %d bytes: action-specific params]' % (len(d) - off))
    print()

    # ===== 0x04 Event =====
    print('=' * 60)
    print('TYPE 0x04 - Event')
    print('=' * 60)
    o = 0x0002880C
    d = data[o:]; sl = struct.unpack_from('<I', d, 1)[0]; d = d[:5 + sl]; off = 5
    oid = struct.unpack_from('<I', d, off)[0]; off += 4
    na = d[off]; off += 1
    print('  objID=0x%08X' % oid)
    print('  numActions=%d' % na)
    for i in range(na):
        aid = struct.unpack_from('<I', d, off)[0]; off += 4
        print('    action[%d]: 0x%08X' % (i, aid))
    print()

    # ===== 0x07 ActorMixer =====
    print('=' * 60)
    print('TYPE 0x07 - ActorMixer')
    print('=' * 60)
    o = 0x0001546B
    d = data[o:]; sl = struct.unpack_from('<I', d, 1)[0]; d = d[:5 + sl]; off = 5
    oid = struct.unpack_from('<I', d, off)[0]; off += 4
    bov = d[off]; off += 1; nfx = d[off]; off += 1
    bat = d[off]; off += 1
    busId = struct.unpack_from('<I', d, off)[0]; off += 4
    par = struct.unpack_from('<I', d, off)[0]; off += 4
    bv = d[off]; off += 1
    print('  objID=0x%08X' % oid)
    print('  NodeBaseParams:')
    print('    bIsOverrideParentFX=%d  uNumFx=%d' % (bov, nfx))
    print('    bOverrideAttachmentParams=%d' % bat)
    print('    overrideBusID=0x%08X' % busId)
    print('    directParentID=0x%08X' % par)
    print('    byBitVector=0x%02X' % bv)
    off, s = pprop(d, off); print('    PropBundle: %s' % s)
    off, s = pranged(d, off); print('    RangedModifiers: %s' % s)
    # Find children at end
    for t in range(off, len(d) - 3):
        n = struct.unpack_from('<I', d, t)[0]
        if 0 < n < 50 and t + 4 + n * 4 == len(d):
            cids = ['0x%08X' % struct.unpack_from('<I', d, t + 4 + i * 4)[0] for i in range(n)]
            print('  numChildren=%d' % n)
            for ci in cids:
                print('    child: %s' % ci)
            break
    print()

    # ===== 0x0B MusicTrack =====
    print('=' * 60)
    print('TYPE 0x0B - MusicTrack (con Volume)')
    print('=' * 60)
    o = 0x03ED5720
    d = data[o:]; sl = struct.unpack_from('<I', d, 1)[0]; d = d[:5 + sl]; off = 5
    oid = struct.unpack_from('<I', d, off)[0]; off += 4
    fl = d[off]; off += 1
    ns = struct.unpack_from('<I', d, off)[0]; off += 4
    print('  objID=0x%08X  flags=0x%02X  numSources=%d' % (oid, fl, ns))
    for s in range(ns):
        pid = struct.unpack_from('<I', d, off)[0]; off += 4
        st = d[off]; off += 1
        sid = struct.unpack_from('<I', d, off)[0]; off += 4
        msz = struct.unpack_from('<I', d, off)[0]; off += 4
        sb = d[off]; off += 1
        print('  Source[%d]: plugin=0x%08X stream=%d srcID=0x%08X media=%d' % (s, pid, st, sid, msz))
    np = struct.unpack_from('<I', d, off)[0]; off += 4
    print('  numPlaylistItems=%d' % np)
    for p in range(np):
        tid = struct.unpack_from('<I', d, off)[0]; off += 4
        sid2 = struct.unpack_from('<I', d, off)[0]; off += 4
        eid = struct.unpack_from('<I', d, off)[0]; off += 4
        pa = struct.unpack_from('<d', d, off)[0]; off += 8
        bt = struct.unpack_from('<d', d, off)[0]; off += 8
        et = struct.unpack_from('<d', d, off)[0]; off += 8
        dur = struct.unpack_from('<d', d, off)[0]; off += 8
        print('    [%d] trackID=0x%08X srcID=0x%08X eventID=0x%08X' % (p, tid, sid2, eid))
        print('        playAt=%.1f beginTrim=%.1f endTrim=%.1f duration=%.2fms' % (pa, bt, et, dur))
    nsub = struct.unpack_from('<I', d, off)[0]; off += 4
    nclip = struct.unpack_from('<I', d, off)[0]; off += 4
    eType = struct.unpack_from('<I', d, off)[0]; off += 4
    bTr = d[off]; off += 1
    TT = {0: 'Normal', 1: 'Random', 2: 'Sequence', 3: 'Switch'}
    print('  numSubTrack=%d  numClipAutomation=%d' % (nsub, nclip))
    print('  eTrackType=%d (%s)  bIsTransitionEnabled=%d' % (eType, TT.get(eType, '?'), bTr))
    # NodeBaseParams for Music types (no bOverrideAttachmentParams / overrideBusId)
    bov = d[off]; off += 1; nfx = d[off]; off += 1
    par = struct.unpack_from('<I', d, off)[0]; off += 4
    bv = d[off]; off += 1
    print('  NodeBaseParams (Music variant):')
    print('    bIsOverrideParentFX=%d  uNumFx=%d' % (bov, nfx))
    print('    directParentID=0x%08X' % par)
    print('    byBitVector=0x%02X' % bv)
    off, s = pprop(d, off); print('    PropBundle: %s' % s)
    off, s = pranged(d, off); print('    RangedModifiers: %s' % s)
    print('  [remaining %d bytes]' % (len(d) - off))
    print()

    # ===== 0x0A MusicSegment =====
    print('=' * 60)
    print('TYPE 0x0A - MusicSegment')
    print('=' * 60)
    o = 0x03E8F6B6
    d = data[o:]; sl = struct.unpack_from('<I', d, 1)[0]; d = d[:5 + sl]; off = 5
    oid = struct.unpack_from('<I', d, off)[0]; off += 4
    print('  objID=0x%08X  secLen=%d' % (oid, sl))
    # MusicSegment has complex MusicNodeParams (NodeBase + positioning + aux + stateChunk + RTPC + children + grid/tempo info) before fDuration/markers.
    # Use heuristic scanning to find fDuration and markers (same as hirc_patcher).
    em = struct.pack('<I', 0x5BBBD648)
    empos = d.find(em)
    if empos >= 0:
        for tt in range(9, empos):
            nm = struct.unpack_from('<I', d, tt)[0]
            if 1 <= nm <= 20:
                p2 = tt + 4; ok = True; last_id = None
                for _ in range(nm):
                    if p2 + 16 > len(d):
                        ok = False; break
                    mid = struct.unpack_from('<I', d, p2)[0]
                    nlen = struct.unpack_from('<I', d, p2 + 12)[0]
                    if nlen > 500:
                        ok = False; break
                    last_id = mid; p2 += 16 + nlen
                if ok and last_id == 0x5BBBD648 and p2 == len(d):
                    fdur = struct.unpack_from('<d', d, tt - 8)[0]
                    print('  [MusicNodeParams: NodeBase + positioning + children + grid]')
                    print('  fDuration=%.2fms' % fdur)
                    print('  numMarkers=%d' % nm)
                    p3 = tt + 4
                    for m in range(nm):
                        mid = struct.unpack_from('<I', d, p3)[0]
                        fpos = struct.unpack_from('<d', d, p3 + 4)[0]
                        mtype = 'END_MARKER' if mid == 0x5BBBD648 else 'marker'
                        print('    [%d] id=0x%08X (%s) fPosition=%.2fms' % (m, mid, mtype, fpos))
                        p3 += 16 + struct.unpack_from('<I', d, p3 + 12)[0]
                    break
    print()

    # ===== 0x0D MusicRanSeqContainer =====
    print('=' * 60)
    print('TYPE 0x0D - MusicRanSeqContainer (Playlist)')
    print('=' * 60)
    o = 0x03EB0813
    d = data[o:]; sl = struct.unpack_from('<I', d, 1)[0]; d = d[:5 + sl]; off = 5
    oid = struct.unpack_from('<I', d, off)[0]; off += 4
    print('  objID=0x%08X  secLen=%d' % (oid, sl))
    print('  [MusicNodeParams: NodeBase + positioning + children + grid]')
    print('  PlaylistTree (30 bytes per item):')
    print('    Struttura per item:')
    print('      segmentID (u32)  - 0 per nodi container, HIRC ID per foglie')
    print('      playlistItemID (u32)')
    print('      numChildren (u32)')
    print('      eRSType (u32)    - 0=RandomContinuous 1=SequentialContinuous')
    print('      loop (s16)       - 0=infinite, 1=play once, N=repeat N')
    print('      loopMin (s16), loopMax (s16)')
    print('      weight (f32)     - prevalence')
    print('      avoidRepeatCount (u16)')
    print('      isUsingWeight (u8), isShuffle (u8)')
    print('    numPlaylistItems (u32) - alla fine della sezione')
    print()

    # ===== Summary of types found =====
    print('=' * 60)
    print('Riepilogo tipi HIRC trovati in Banks1.pck')
    print('=' * 60)
    type_counts = {}
    pos = 0
    while True:
        p = data.find(b'HIRC', pos)
        if p == -1:
            break
        sec_len = struct.unpack_from('<I', data, p + 4)[0]
        if sec_len < 4 or p + 8 + sec_len > len(data):
            pos = p + 1; continue
        num_obj = struct.unpack_from('<I', data, p + 8)[0]
        obj_pos = p + 12; sec_end = p + 8 + sec_len
        for _ in range(num_obj):
            if obj_pos + 5 > sec_end:
                break
            ot = data[obj_pos]
            os2 = struct.unpack_from('<I', data, obj_pos + 1)[0]
            type_counts[ot] = type_counts.get(ot, 0) + 1
            obj_pos = obj_pos + 5 + os2
        pos = p + 1
    TN = {0x01: 'Settings/State', 0x02: 'Sound SFX', 0x03: 'Event Action',
          0x04: 'Event', 0x05: 'RandomSeqContainer', 0x06: 'SwitchContainer',
          0x07: 'ActorMixer', 0x08: 'AudioBus', 0x09: 'BlendContainer',
          0x0A: 'MusicSegment', 0x0B: 'MusicTrack', 0x0C: 'MusicSwitchContainer',
          0x0D: 'MusicRanSeqContainer', 0x0E: 'Attenuation', 0x10: 'FeedbackBus',
          0x11: 'FxShareSet', 0x13: 'AuxBus', 0x16: 'AudioDevice'}
    for t in sorted(type_counts):
        print('  0x%02X  %-25s  %d objects' % (t, TN.get(t, 'Unknown'), type_counts[t]))


if __name__ == '__main__':
    main()
