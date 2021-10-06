import React from 'react';
import api from 'api';
import './tv_wall.css';

class Tv extends React.Component {

  constructor(props) {
    super(props);
    this.apiClient = new api();
    this.state = {
      display_mode: this.props.display_mode,
    };
    this.handleSetDisplayMode = this.handleSetDisplayMode.bind(this);
  }

  render() {
    return (
      <div className='tv' style={{
          top: this.props.y,
          left: this.props.x,
          width: this.props.width,
          height: this.props.height,
          backgroundImage: `url(${this.props.src})`,
          backgroundPosition: `-${this.props.x}px -${this.props.y}px`,
          backgroundSize: `${this.props.bgImgWidth}px ${this.props.bgImgHeight}px`,
        }}
        onClick={this.handleSetDisplayMode}
      >
      </div>
    );
  }

  handleSetDisplayMode(e) {
    e.preventDefault();
    let new_display_mode = 'DISPLAY_MODE_TILE';
    if (this.state.display_mode == 'DISPLAY_MODE_TILE') {
      new_display_mode = 'DISPLAY_MODE_REPEAT';
    }
    const tvs = [{hostname: this.props.hostname, tv_id: this.props.id}];
    this.apiClient.setReceiversDisplayMode(tvs, new_display_mode)
      .then((data) => {
        this.setState({display_mode: new_display_mode})
      });
  }

}

export default Tv;
