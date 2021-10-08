import React from 'react';
import './tv_wall.css';

class Tv extends React.Component {

  constructor(props) {
    super(props);
    this.toggleDisplayMode = this.toggleDisplayMode.bind(this);
  }

  render() {
    let background_size, background_position;
    if (this.state.display_mode === 'DISPLAY_MODE_TILE') {
      background_size = this.props.bgImgWidth + 'px ' + this.props.bgImgHeight + 'px';
      background_position = '-' + this.props.x + 'px -' + this.props.y + 'px';
    } else {
      background_size = 'contain';
      background_position = 'top left';
    }

    return (
      <div className='tv' style={{
          top: this.props.y,
          left: this.props.x,
          width: this.props.width,
          height: this.props.height,
          backgroundImage: `url(${this.props.src})`,
          backgroundPosition: background_position,
          backgroundSize: background_size,
        }}
        onClick={this.toggleDisplayMode}
      >
      </div>
    );
  }

  toggleDisplayMode(e) {
    e.preventDefault();
    let new_display_mode = 'DISPLAY_MODE_TILE';
    if (this.props.display_mode === 'DISPLAY_MODE_TILE') {
      new_display_mode = 'DISPLAY_MODE_REPEAT';
    }
    const display_mode_by_tv_id = {this.props.tv_id: new_display_mode};
    this.props.setDisplayMode(display_mode_by_tv_id);
  }

}

export default Tv;
