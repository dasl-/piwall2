import React from 'react';
import api from 'api';

import TV from 'component/app/tv';

import config from 'receivers_config.json';
import './wall.css';

class Wall extends React.Component {

  constructor(props) {
    super(props);

    this.apiClient = new api();

    this.state = config;
  }


  render() {
    // hostname: "piwall2.local"
    // tv_id: 1
    // height: 8.25
    // width: 11
    // x: 0
    // y: 0.5
    let wallHeight = this.state.wall_height;
    let wallWidth = this.state.wall_width;

    let imgWidth = 320;
    let imgHeight = 180;
    let scale = imgHeight / wallHeight;

    let offsetX = (imgWidth - (wallWidth * scale)) / 2;
    let offsetY = 0;

    let src = this.props.src;

    return (
      <div className="wallContainer" style={
        {
          width: imgWidth,
          height: imgHeight,
        }
        }>
        <div className='wall' style={
          {
            width: imgWidth,
            height: imgHeight,

            backgroundImage: `url(${src})`,
          }
          } />
        <div className="tvs" style={
          {
            width: imgWidth,
            height: imgHeight,
            left: offsetX,
            top: offsetY
          }
          } >
          {
            this.state.tvs.map((tv, index) => {
              return (
                <TV
                  key={index}
                  scale={scale}
                  src={src}
                  id={tv.tv_id}
                  height={tv.height}
                  hostname={tv.hostname}
                  width={tv.width}
                  offsetX={offsetX}
                  offsetY={offsetY}
                  x={tv.x}
                  y={tv.y}
                />
              );
            })
          }
        </div>
      </div>
    );
  }
}

export default Wall;