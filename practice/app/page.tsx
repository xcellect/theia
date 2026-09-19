import PracticeVoice from "../components/PracticeVoice";

export default function Page() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#practice">Skip to voice practice</a>
      <header className="site-header">
        <a className="wordmark" href="/" aria-label="Voice AI practice home">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /><i /></span>
          <span>Voice AI <span className="wordmark-subtle">· Practice</span></span>
        </a>
        <span className="practice-label">PRE-EVENT SANDBOX</span>
      </header>

      <main id="practice">
        <section className="intro" aria-labelledby="page-title">
          <p className="eyebrow"><span /> A SPACE TO TEST THE BASICS</p>
          <h1 id="page-title">Start with a<br /><em>conversation.</em></h1>
          <p className="intro-description">Check your microphone, hear a response, and follow the words.<br className="desktop-break" /> A small rehearsal before the real build.</p>
        </section>

        <PracticeVoice />

        <section className="practice-notes" aria-label="Practice checklist">
          <article><span className="note-number">01</span><div><h3>Bring your own voice</h3><p>Use your laptop and headset. Allow microphone access when you start the session.</p></div></article>
          <article><span className="note-number">02</span><div><h3>Try three turns</h3><p>Say hello, ask a follow-up, then interrupt a reply. End the session and check the mic stops.</p></div></article>
          <article><span className="note-number">03</span><div><h3>Compare the three routes</h3><p>End your session, choose another voice stack, then ask the same question.</p></div></article>
        </section>
      </main>

      <footer className="site-footer"><span>Built for practice. Ready to learn.</span><span>Hume EVI <span className="footer-divider">/</span> SambaNova + Hume <span className="footer-divider">/</span> General Compute + Gradium</span></footer>
    </div>
  );
}
