using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.CompilerServices;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using WixSharp;
using WixSharp.UI.WPF;

namespace XXAR.Installer.Dialogs
{
    public partial class XXARLicenceDialog : WpfDialog, IWpfDialog
    {
        private Model model;

        public XXARLicenceDialog()
        {
            InitializeComponent();
            XXARHostStyling.RegisterDarkWpfCompositionTarget(this);
        }

        public void Init()
        {
            XXARHostStyling.ApplyDarkHost(ManagedFormHost);
            model = new Model(this) { Host = ManagedFormHost };
            DataContext = model;
            model.LoadRtfInto(LicenceText);
        }

        private void GoPrev_Click(object sender, RoutedEventArgs e) => model.GoPrev();
        private void GoNext_Click(object sender, RoutedEventArgs e) => model.GoNext();
        private void Cancel_Click(object sender, RoutedEventArgs e) => model.Cancel();

        // Re-implements the stock LicenseDialogModel since it is internal.
        private class Model : INotifyPropertyChanged
        {
            private readonly XXARLicenceDialog view;
            public Model(XXARLicenceDialog view) { this.view = view; }

            public WixSharp.UI.Forms.ManagedForm Host;
            private ISession session => Host?.Runtime?.Session;
            private IManagedUIShell shell => Host?.Shell;

            public bool LicenseAcceptedChecked
            {
                get => session?["LastLicenceAcceptedChecked"] == "True";
                set
                {
                    if (Host != null)
                        session["LastLicenceAcceptedChecked"] = value.ToString();
                    OnChanged();
                }
            }

            public void LoadRtfInto(RichTextBox rtb)
            {
                var rtf = session?.GetResourceString("WixSharp_LicenceFile");
                if (string.IsNullOrEmpty(rtf))
                    return;
                var bytes = Encoding.UTF8.GetBytes(rtf);
                using (var stream = new MemoryStream(bytes))
                {
                    rtb.SelectAll();
                    rtb.Selection.Load(stream, DataFormats.Rtf);
                }
            }

            public void GoPrev() => shell?.GoPrev();
            public void GoNext() => shell?.GoNext();
            public void Cancel() => shell?.Cancel();

            public event PropertyChangedEventHandler PropertyChanged;
            private void OnChanged([CallerMemberName] string name = null)
                => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
        }
    }
}
