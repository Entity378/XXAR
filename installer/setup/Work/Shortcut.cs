using System;
using System.Runtime.InteropServices;

namespace XXAR.Setup
{
    // Writes .lnk files through the shell's own IShellLink, the API every installer uses.
    public static class Shortcut
    {
        public static void Write(string linkPath, string target, string workingFolder, string description)
        {
            var link = (IShellLinkW)new ShellLinkCoClass();
            try
            {
                link.SetPath(target);
                link.SetWorkingDirectory(workingFolder);
                link.SetDescription(description);
                link.SetIconLocation(target, 0);
                ((IPersistFile)link).Save(linkPath, true);
            }
            finally
            {
                Marshal.ReleaseComObject(link);
            }
        }

        [ComImport, Guid("00021401-0000-0000-C000-000000000046"), ClassInterface(ClassInterfaceType.None)]
        private class ShellLinkCoClass { }

        // Only the setters are called; the rest keep the vtable slots in their documented order.
        [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IShellLinkW
        {
            void GetPath(IntPtr file, int maxPath, IntPtr findData, uint flags);
            void GetIDList(out IntPtr idList);
            void SetIDList(IntPtr idList);
            void GetDescription(IntPtr name, int maxName);
            void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string name);
            void GetWorkingDirectory(IntPtr folder, int maxPath);
            void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string folder);
            void GetArguments(IntPtr arguments, int maxArguments);
            void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string arguments);
            void GetHotkey(out short hotkey);
            void SetHotkey(short hotkey);
            void GetShowCmd(out int showCommand);
            void SetShowCmd(int showCommand);
            void GetIconLocation(IntPtr iconPath, int maxPath, out int iconIndex);
            void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string iconPath, int iconIndex);
            void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string relativePath, uint reserved);
            void Resolve(IntPtr window, uint flags);
            void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
        }

        [ComImport, Guid("0000010B-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IPersistFile
        {
            void GetClassID(out Guid classId);
            [PreserveSig] int IsDirty();
            void Load([MarshalAs(UnmanagedType.LPWStr)] string fileName, uint mode);
            void Save([MarshalAs(UnmanagedType.LPWStr)] string fileName, [MarshalAs(UnmanagedType.Bool)] bool remember);
            void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string fileName);
            void GetCurFile(out IntPtr fileName);
        }
    }
}
