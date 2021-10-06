import React from 'react';
import './tv_wall.css';

class Tv extends React.Component {

  constructor(props) {
    super(props);
    this.state = {};
  }

  render() {
    return (
      <div className='tv' style={
        {
          top: this.props.y,
          left: this.props.x,
          width: this.props.width,
          height: this.props.height,
          backgroundImage: `url(${this.props.src})`,
          backgroundPosition: `-${this.props.x}px -${this.props.y}px`,
          backgroundSize: `${this.props.bgImgWidth}px ${this.props.bgImgHeight}px`
        }
        }>
      </div>
    );
  }

  // TODO...
  handleSetDisplayMode(e, receiver_hostname, tv_id, display_mode) {
    e.preventDefault();
    const tvs = [{hostname: receiver_hostname, tv_id: tv_id}];
    this.apiClient.setReceiversDisplayMode(tvs, display_mode)
      .then((data) => {
        // TODO: return the new display modes and update UI
      });
  }

}

export default Tv;
