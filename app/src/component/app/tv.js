import React from 'react';
import api from 'api';

class TV extends React.Component {

  constructor(props) {
    super(props);

    this.apiClient = new api();

    this.state = {};
  }

  render() {
    let props = this.props;
    let scale = props.scale;
    let bgPos = "-" + ((props.x * scale) + props.offsetX) + "px -" + ((props.y * scale) + props.offsetY) + "px";

    return (
      <div className='tv' style={
        {
          top:(props.y * scale),
          left:(props.x * scale),
          width:props.width * scale,
          height:props.height * scale,
          backgroundImage: `url(https://i.ytimg.com/vi/IcxWyfGR-2A/mqdefault.jpg)`,
          backgroundPosition: bgPos
        }
        }>
      </div>
    );
  }
}

export default TV;