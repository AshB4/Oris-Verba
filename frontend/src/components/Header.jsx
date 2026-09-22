import logo from "../assets/OV.png";

function Header() {
  return (
    <header className="app-header">
      <div className="brand-lockup">
        <div className="brand-mark">
          <div className="logo-glow" aria-hidden="true" />
          <img className="brand-logo" src={logo} alt="Oris Verba" width="181" height="136" />
        </div>
        <div className="brand-copy">
          <p className="brand-name">Oris Verba</p>
          <h1>Turn every word into text.</h1>
          <p className="brand-support">Private transcription for live conversations and local recordings.</p>
        </div>
      </div>

      <div className="local-badge" title="Audio stays on this computer">
        <span className="privacy-dot" aria-hidden="true" />
        <span>
          <strong>Local only</strong>
          <small>Private by design</small>
        </span>
      </div>
    </header>
  );
}

export default Header;
