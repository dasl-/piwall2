import React from 'react';
import './tv_wall.css';

class Tv extends React.Component {

  constructor(props) {
    super(props);
    this.toggleDisplayMode = this.toggleDisplayMode.bind(this);
  }

  render() {
    const backgroundPosition = this.props.display_mode === 'DISPLAY_MODE_FULLSCREEN' ?
      this.props.displayModeFullscreenBgPos : this.props.displayModeTileBgPos;
    const backgroundSize = this.props.display_mode === 'DISPLAY_MODE_FULLSCREEN' ?
      this.props.displayModeFullscreenBgSize : this.props.displayModeTileBgSize;
    const maybe_loading_class = this.props.loading ? 'loading' : '';

    return (
      <div className={'tv-wrapper bg-dark ' + maybe_loading_class} style={{
        top: this.props.y,
        left: this.props.x,
        width: this.props.width,
        height: this.props.height,
      }}>
        <div className='loading-cover'><div className='dot-pulse'></div></div>
        <div className='tv' style={{
            width: this.props.width,
            height: this.props.height,
            backgroundImage: `url(${this.props.src})`,
            backgroundPosition: backgroundPosition,
            backgroundSize: backgroundSize,
          }}
          onClick={this.toggleDisplayMode}
        >
        </div>
      </div>
    );
  }

  toggleDisplayMode(e) {
    e.preventDefault();
    let new_display_mode = 'DISPLAY_MODE_FULLSCREEN';
    if (this.props.display_mode === 'DISPLAY_MODE_FULLSCREEN') {
      new_display_mode = 'DISPLAY_MODE_TILE';
    }
    let display_mode_by_tv_id = {};
    display_mode_by_tv_id[this.props.tv_id] = new_display_mode;
    this.props.setDisplayMode(display_mode_by_tv_id);
  }

}

export default Tv;
